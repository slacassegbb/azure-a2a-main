import { NextResponse } from "next/server"

export async function GET() {
  try {
    const apiKey = process.env.AZURE_VOICE_API_KEY || process.env.AZURE_OPENAI_GPT_API_KEY
    if (!apiKey) throw new Error("AZURE_VOICE_API_KEY or AZURE_OPENAI_GPT_API_KEY not found")
    return NextResponse.json({ token: apiKey })
  } catch (error: any) {
    return NextResponse.json({ error: "Failed to get Azure API key", details: error.message }, { status: 500 })
  }
}
