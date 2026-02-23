import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'

const execAsync = promisify(exec)

export async function GET() {
  try {
    // Use voice-specific key if available, fall back to general Azure OpenAI key
    const apiKey = process.env.AZURE_VOICE_API_KEY || process.env.AZURE_OPENAI_GPT_API_KEY

    if (!apiKey) {
      throw new Error('AZURE_VOICE_API_KEY or AZURE_OPENAI_GPT_API_KEY not found in environment')
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

