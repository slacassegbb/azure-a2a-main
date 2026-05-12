import { NextRequest, NextResponse } from "next/server";
import { BlobServiceClient } from "@azure/storage-blob";

const CONN_STR = process.env.IOT_BLOB_CONNECTION_STRING || "";
const CONTAINER = process.env.IOT_BLOB_CONTAINER || "garden-images";
const USER_ID = process.env.GARDEN_USER_ID || "user_3";

export async function POST(request: NextRequest) {
  if (!CONN_STR) return NextResponse.json({ error: "Not configured" }, { status: 500 });

  const { user, agent } = await request.json();
  if (!user || !agent) return NextResponse.json({ error: "user and agent required" }, { status: 400 });

  const client = BlobServiceClient.fromConnectionString(CONN_STR);
  const container = client.getContainerClient(CONTAINER);
  const blobName = `voice-log-${USER_ID}.json`;

  // Read existing log
  let entries: any[] = [];
  try {
    const blob = container.getBlobClient(blobName);
    const response = await blob.download(0);
    const chunks: Buffer[] = [];
    for await (const chunk of response.readableStreamBody as any) chunks.push(Buffer.from(chunk));
    entries = JSON.parse(Buffer.concat(chunks).toString()).entries || [];
  } catch { /* no existing log */ }

  // Append new entry, keep last 100
  entries.push({ timestamp: new Date().toISOString(), user, agent });
  if (entries.length > 100) entries = entries.slice(-100);

  const payload = JSON.stringify({ entries });
  await container.getBlockBlobClient(blobName).upload(payload, payload.length, {
    blobHTTPHeaders: { blobContentType: "application/json" },
  });

  return NextResponse.json({ success: true });
}
