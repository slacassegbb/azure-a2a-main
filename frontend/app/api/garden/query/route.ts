import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_A2A_API_URL || "https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io";

export async function POST(request: NextRequest) {
  const { query } = await request.json();
  if (!query) return NextResponse.json({ error: "query required" }, { status: 400 });

  try {
    const loginRes = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "test@example.com", password: "test123" }),
    });
    const { access_token } = await loginRes.json();

    const queryRes = await fetch(`${BACKEND_URL}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
      body: JSON.stringify({
        query: `CHAT_MODE: ${query}`,
        user_id: "user_3",
        session_id: "user_3",
        enable_routing: true,
        timeout: 600,
        activated_agents: ["Home Gardening Agent"],
      }),
    });
    const data = await queryRes.json();
    return NextResponse.json({ result: data.result || "Done." });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
