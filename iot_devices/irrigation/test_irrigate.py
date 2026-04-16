"""
Test the irrigation device by writing commands to Azure Blob Storage.
Same storage account as the vision device.

Usage:
  # Trigger irrigation (default 2 minutes)
  python3 test_irrigate.py irrigate

  # Trigger with custom duration (in seconds)
  python3 test_irrigate.py irrigate 30

  # Check current command state
  python3 test_irrigate.py status

  # Reset (set irrigate to false, so you can trigger again)
  python3 test_irrigate.py reset
"""

import json
import sys
import uuid
from azure.storage.blob import BlobServiceClient, ContentSettings

CONN_STR  = "DefaultEndpointsProtocol=https;AccountName=a2astoragefilesa2a;AccountKey=CS6udqgXa//vXxtg2oPUGiXrQooHaIPVNqsLD0g8WAO09dTBm4zHm0SCkMDSIRmpTbZBrOjg33q8+AStPTyYGw==;EndpointSuffix=core.windows.net"
CONTAINER = "garden-images"
BLOB_NAME = "irrigation-command.json"


def get_blob_client():
    svc = BlobServiceClient.from_connection_string(CONN_STR)
    return svc.get_container_client(CONTAINER).get_blob_client(BLOB_NAME)


def read_command():
    blob = get_blob_client()
    try:
        data = blob.download_blob().readall()
        return json.loads(data)
    except Exception:
        return {"request_id": "", "irrigate": False}


def write_command(cmd):
    blob = get_blob_client()
    blob.upload_blob(
        json.dumps(cmd),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_irrigate.py [irrigate|status|reset]")
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "status":
        cmd = read_command()
        print(json.dumps(cmd, indent=2))

    elif action == "irrigate":
        duration_s = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        duration_ms = duration_s * 1000
        cmd = {"request_id": str(uuid.uuid4())[:8], "irrigate": True, "duration_ms": duration_ms}
        write_command(cmd)
        print(f"Sent irrigate command: {cmd['request_id']} ({duration_s}s)")
        print("ESP32 will pick this up within 5 seconds.")

    elif action == "reset":
        cmd = read_command()
        cmd["irrigate"] = False
        write_command(cmd)
        print(f"Reset. request_id kept: {cmd['request_id']}")

    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
