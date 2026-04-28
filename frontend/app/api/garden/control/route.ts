import { NextRequest, NextResponse } from "next/server";
import { BlobServiceClient } from "@azure/storage-blob";
import { randomUUID } from "crypto";

const CONN_STR = process.env.IOT_BLOB_CONNECTION_STRING || "";
const CONTAINER = process.env.IOT_BLOB_CONTAINER || "garden-images";

async function writeBlob(blobName: string, data: any) {
  const client = BlobServiceClient.fromConnectionString(CONN_STR);
  const container = client.getContainerClient(CONTAINER);
  const blob = container.getBlockBlobClient(blobName);
  await blob.upload(JSON.stringify(data), JSON.stringify(data).length, {
    blobHTTPHeaders: { blobContentType: "application/json" },
  });
}

export async function POST(request: NextRequest) {
  if (!CONN_STR) {
    return NextResponse.json({ error: "IOT_BLOB_CONNECTION_STRING not configured" }, { status: 500 });
  }

  const body = await request.json();
  const { action } = body;
  const requestId = randomUUID().slice(0, 8);

  try {
    switch (action) {
      case "irrigate_valve": {
        const { valve = "a", duration_seconds = 120 } = body;
        await writeBlob("valve-command.json", { request_id: requestId, valve, duration_seconds });
        return NextResponse.json({ success: true, request_id: requestId, message: `Valve ${valve.toUpperCase()} + pump for ${duration_seconds}s` });
      }
      case "set_fan": {
        const { state = false, speed = 100 } = body;
        await writeBlob("fan-command.json", { request_id: requestId, state, speed });
        return NextResponse.json({ success: true, request_id: requestId, message: `Fan ${state ? `ON at ${speed}%` : "OFF"}` });
      }
      case "set_light_brightness": {
        // Read current schedule, update peak brightness
        const client = BlobServiceClient.fromConnectionString(CONN_STR);
        const container = client.getContainerClient(CONTAINER);
        let schedule: any = {};
        try {
          const buf = await container.getBlobClient("light-schedule.json").downloadToBuffer();
          schedule = JSON.parse(buf.toString());
        } catch { /* use defaults */ }
        schedule.request_id = requestId;
        schedule.peak_brightness = body.brightness ?? 100;
        schedule.night_brightness = body.brightness ?? 0; // also set night if adjusting manually
        await writeBlob("light-schedule.json", schedule);
        return NextResponse.json({ success: true, request_id: requestId, message: `Light brightness set to ${body.brightness}%` });
      }
      case "set_light_power": {
        const client = BlobServiceClient.fromConnectionString(CONN_STR);
        const container = client.getContainerClient(CONTAINER);
        let schedule: any = {};
        try {
          const buf = await container.getBlobClient("light-schedule.json").downloadToBuffer();
          schedule = JSON.parse(buf.toString());
        } catch { /* use defaults */ }
        schedule.request_id = requestId;
        if (!body.state) {
          schedule.peak_brightness = 0;
          schedule.night_brightness = 0;
        } else {
          schedule.peak_brightness = 100;
          schedule.night_brightness = 0;
        }
        await writeBlob("light-schedule.json", schedule);
        return NextResponse.json({ success: true, request_id: requestId, message: `Light ${body.state ? "ON" : "OFF"}` });
      }
      case "set_light_schedule": {
        const clientLS = BlobServiceClient.fromConnectionString(CONN_STR);
        const containerLS = clientLS.getContainerClient(CONTAINER);
        let scheduleLS: any = {};
        try {
          const response = await containerLS.getBlobClient("light-schedule.json").download(0);
          const chunks: Buffer[] = [];
          for await (const chunk of response.readableStreamBody as any) chunks.push(Buffer.from(chunk));
          scheduleLS = JSON.parse(Buffer.concat(chunks).toString());
        } catch { /* defaults */ }
        scheduleLS.request_id = requestId;
        if (body.sunrise_hour !== undefined) scheduleLS.sunrise_hour = body.sunrise_hour;
        if (body.sunset_hour !== undefined) scheduleLS.sunset_hour = body.sunset_hour;
        await writeBlob("light-schedule.json", scheduleLS);
        return NextResponse.json({ success: true, request_id: requestId, message: `Schedule updated: sunrise ${scheduleLS.sunrise_hour}h, sunset ${scheduleLS.sunset_hour}h` });
      }
      case "set_humidifier": {
        // Route through backend to gardening agent
        const { action: humAction = "status", target_humidity } = body;
        const backendUrl = "https://backend-uami.ambitioussky-6c709152.westus2.azurecontainerapps.io";
        const query = humAction === "off"
          ? "Use the control_humidifier tool to turn off the humidifier"
          : target_humidity
          ? `Use the control_humidifier tool to set humidifier to auto mode targeting ${target_humidity}% humidity`
          : "Use the control_humidifier tool to turn on the humidifier";
        try {
          const loginRes = await fetch(`${backendUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: "test@example.com", password: "test123" }),
          });
          const { access_token } = await loginRes.json();
          const queryRes = await fetch(`${backendUrl}/api/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": `Bearer ${access_token}` },
            body: JSON.stringify({
              query,
              user_id: "user_3",
              session_id: "user_3",
              enable_routing: true,
              activated_agents: ["Home Gardening Agent"],
            }),
          });
          const result = await queryRes.json();
          return NextResponse.json({ success: true, message: result.result || "Humidifier command sent" });
        } catch (e: any) {
          return NextResponse.json({ success: false, message: `Failed: ${e.message}` });
        }
      }
      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
