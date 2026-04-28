import { NextRequest, NextResponse } from "next/server";
import { BlobServiceClient } from "@azure/storage-blob";

const CONN_STR = process.env.IOT_BLOB_CONNECTION_STRING || "";
const CONTAINER = process.env.IOT_BLOB_CONTAINER || "garden-images";
const USER_ID = process.env.GARDEN_USER_ID || "user_3";

function getBlobName() {
  return `garden-config-${USER_ID}.json`;
}

export async function GET() {
  if (!CONN_STR) return NextResponse.json({ description: "" });
  try {
    const client = BlobServiceClient.fromConnectionString(CONN_STR);
    const container = client.getContainerClient(CONTAINER);
    const blob = container.getBlobClient(getBlobName());
    const response = await blob.download(0);
    const chunks: Buffer[] = [];
    for await (const chunk of response.readableStreamBody as any) {
      chunks.push(Buffer.from(chunk));
    }
    const data = JSON.parse(Buffer.concat(chunks).toString());
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ description: "" });
  }
}

export async function POST(request: NextRequest) {
  if (!CONN_STR) return NextResponse.json({ error: "Not configured" }, { status: 500 });
  const body = await request.json();
  const data = { description: body.description || "", updated_at: new Date().toISOString() };

  const client = BlobServiceClient.fromConnectionString(CONN_STR);
  const container = client.getContainerClient(CONTAINER);
  const blob = container.getBlockBlobClient(getBlobName());
  await blob.upload(JSON.stringify(data), JSON.stringify(data).length, {
    blobHTTPHeaders: { blobContentType: "application/json" },
  });
  return NextResponse.json({ success: true });
}
