import { NextResponse } from "next/server";
import {
  BlobServiceClient,
  StorageSharedKeyCredential,
  generateBlobSASQueryParameters,
  BlobSASPermissions,
} from "@azure/storage-blob";

const CONN_STR = process.env.IOT_BLOB_CONNECTION_STRING || "";
const CONTAINER = process.env.IOT_BLOB_CONTAINER || "garden-images";
const USER_ID = process.env.GARDEN_USER_ID || "user_3";

function getClient() {
  return BlobServiceClient.fromConnectionString(CONN_STR);
}

async function readJsonBlob(containerClient: any, blobName: string) {
  try {
    const blob = containerClient.getBlobClient(blobName);
    const response = await blob.download(0);
    const chunks: Buffer[] = [];
    for await (const chunk of response.readableStreamBody as any) {
      chunks.push(Buffer.from(chunk));
    }
    return JSON.parse(Buffer.concat(chunks).toString());
  } catch (e: any) {
    console.error(`[Garden API] Failed to read ${blobName}:`, e.message);
    return null;
  }
}

function generateSasUrl(containerClient: any, blobName: string, expiryMinutes: number): string | null {
  try {
    // Parse account name and key from connection string
    const parts = CONN_STR.split(";").reduce((acc: Record<string, string>, part) => {
      const [key, ...rest] = part.split("=");
      acc[key] = rest.join("=");
      return acc;
    }, {});
    const accountName = parts["AccountName"];
    const accountKey = parts["AccountKey"];
    if (!accountName || !accountKey) return null;

    const cred = new StorageSharedKeyCredential(accountName, accountKey);
    const expiresOn = new Date(Date.now() + expiryMinutes * 60 * 1000);
    const sas = generateBlobSASQueryParameters(
      {
        containerName: CONTAINER,
        blobName,
        permissions: BlobSASPermissions.parse("r"),
        expiresOn,
      },
      cred
    ).toString();
    return `https://${accountName}.blob.core.windows.net/${CONTAINER}/${blobName}?${sas}`;
  } catch {
    return null;
  }
}

async function listRecentPhotos(containerClient: any, maxPhotos: number = 20): Promise<any[]> {
  const photos: any[] = [];
  const regex = /^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.(jpg|jpeg|png)$/;
  try {
    for await (const blob of containerClient.listBlobsFlat()) {
      if (regex.test(blob.name)) {
        photos.push({ name: blob.name, lastModified: blob.properties.lastModified });
      }
    }
    photos.sort((a, b) => new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime());
    return photos.slice(0, maxPhotos).map((p) => ({
      name: p.name,
      url: generateSasUrl(containerClient, p.name, 60) || "",
      timestamp: p.lastModified?.toISOString() || "",
    }));
  } catch {
    return [];
  }
}

export async function GET() {
  if (!CONN_STR) {
    return NextResponse.json({ error: "IOT_BLOB_CONNECTION_STRING not configured" }, { status: 500 });
  }

  const client = getClient();
  const container = client.getContainerClient(CONTAINER);

  const [moisture, lightSchedule, fan, valve, irrigation, gardenLog, cameraProps, photos, humidifier] =
    await Promise.allSettled([
      readJsonBlob(container, "moisture-data.json"),
      readJsonBlob(container, "light-schedule.json"),
      readJsonBlob(container, "fan-command.json"),
      readJsonBlob(container, "valve-command.json"),
      readJsonBlob(container, "irrigation-command.json"),
      readJsonBlob(container, `garden-log-${USER_ID}.json`),
      container.getBlobClient("latest.jpg").getProperties().catch(() => null),
      listRecentPhotos(container, 20),
      readJsonBlob(container, "humidifier-status.json"),
    ]);

  const resolve = (r: PromiseSettledResult<any>) => (r.status === "fulfilled" ? r.value : null);

  const cameraUrl = generateSasUrl(container, "latest.jpg", 60);
  const cameraMeta = resolve(cameraProps);

  return NextResponse.json({
    timestamp: new Date().toISOString(),
    moisture: resolve(moisture),
    light_schedule: resolve(lightSchedule),
    fan: resolve(fan),
    valve: resolve(valve),
    irrigation: resolve(irrigation),
    camera_url: cameraUrl,
    camera_timestamp: cameraMeta?.lastModified?.toISOString() || null,
    garden_log: resolve(gardenLog)?.entries || [],
    photos: resolve(photos) || [],
    humidifier: resolve(humidifier),
  });
}
