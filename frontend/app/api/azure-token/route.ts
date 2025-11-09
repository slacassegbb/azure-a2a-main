import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'

const execAsync = promisify(exec)

export async function GET() {
  try {
    // For Voice Live API, use the Azure OpenAI API key from environment
    const apiKey = process.env.AZURE_OPENAI_GPT_API_KEY

    if (!apiKey) {
      throw new Error('AZURE_OPENAI_GPT_API_KEY not found in environment')
    }

    console.log('[Azure Token API] API key fetched successfully from environment')

    return NextResponse.json({ token: apiKey })
  } catch (error: any) {
    console.error('[Azure Token API] Failed to get API key:', error)
    return NextResponse.json(
      { 
        error: 'Failed to get Azure API key',
        details: error.message 
      },
      { status: 500 }
    )
  }
}

