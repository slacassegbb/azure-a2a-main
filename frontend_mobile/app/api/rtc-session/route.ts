import { NextResponse } from "next/server"

export async function POST(req: Request) {
  try {
    const { sdp } = await req.json()
    if (!sdp) return NextResponse.json({ error: "Missing SDP offer" }, { status: 400 })

    const apiKey = process.env.AZURE_VOICE_API_KEY || process.env.AZURE_OPENAI_GPT_API_KEY
    if (!apiKey) throw new Error("AZURE_VOICE_API_KEY or AZURE_OPENAI_GPT_API_KEY not configured")

    const voiceHost = process.env.NEXT_PUBLIC_VOICE_HOST
    const deployment = process.env.NEXT_PUBLIC_VOICE_DEPLOYMENT || "gpt-realtime"
    if (!voiceHost) throw new Error("NEXT_PUBLIC_VOICE_HOST not configured")

    const baseUrl = `https://${voiceHost}/openai/v1/realtime`

    // Step 1: Get ephemeral token from Azure (keeps API key server-side)
    const tokenRes = await fetch(`${baseUrl}/client_secrets`, {
      method: "POST",
      headers: { "api-key": apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({
        session: { type: "realtime", model: deployment },
      }),
    })

    if (!tokenRes.ok) {
      const detail = await tokenRes.text()
      console.error("[rtc-session] Token request failed:", tokenRes.status, detail)
      return NextResponse.json(
        { error: `Token request failed: ${tokenRes.status}`, detail },
        { status: tokenRes.status }
      )
    }

    const tokenData = await tokenRes.json()
    // Azure returns { value: "ek_..." } directly (not nested under client_secret)
    const ephemeralToken = tokenData.value || tokenData.client_secret?.value
    if (!ephemeralToken) {
      console.error("[rtc-session] No ephemeral token in response:", JSON.stringify(tokenData))
      throw new Error("No ephemeral token in response")
    }

    // Step 2: Exchange SDP offer for answer using ephemeral token
    const sdpRes = await fetch(`${baseUrl}/calls`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ephemeralToken}`,
        "Content-Type": "application/sdp",
      },
      body: sdp,
    })

    if (!sdpRes.ok) {
      const detail = await sdpRes.text()
      console.error("[rtc-session] SDP exchange failed:", sdpRes.status, detail)
      return NextResponse.json(
        { error: `SDP exchange failed: ${sdpRes.status}`, detail },
        { status: sdpRes.status }
      )
    }

    const answerSdp = await sdpRes.text()
    return NextResponse.json({ sdp: answerSdp })
  } catch (error: any) {
    console.error("[rtc-session] Error:", error)
    return NextResponse.json({ error: error.message || "RTC session failed" }, { status: 500 })
  }
}
