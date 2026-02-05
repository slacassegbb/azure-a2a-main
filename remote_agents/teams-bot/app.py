import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from botbuilder.core import (
    BotFrameworkAdapterSettings,
    BotFrameworkAdapter,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes, ConversationReference
from botframework.connector.auth import MicrosoftAppCredentials

load_dotenv()

MICROSOFT_APP_ID = os.getenv("MICROSOFT_APP_ID", "")
MICROSOFT_APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "")
MICROSOFT_APP_TENANT_ID = os.getenv("MICROSOFT_APP_TENANT_ID", "")

app = FastAPI()

# Create custom credentials class for Single Tenant authentication
class SingleTenantAppCredentials(MicrosoftAppCredentials):
    def __init__(self, app_id: str, app_password: str, tenant_id: str):
        super().__init__(app_id, app_password)
        # Override OAuth endpoint to use tenant-specific authority (not the full token URL)
        self.oauth_endpoint = f"https://login.microsoftonline.com/{tenant_id}"
        self.oauth_scope = "https://api.botframework.com/.default"

# Configure adapter with tenant-aware credentials
settings = BotFrameworkAdapterSettings(MICROSOFT_APP_ID, MICROSOFT_APP_PASSWORD)

# Override the credential provider if we have a tenant ID
if MICROSOFT_APP_TENANT_ID:
    # Create instance of our custom credentials
    settings.app_credentials = SingleTenantAppCredentials(
        MICROSOFT_APP_ID, 
        MICROSOFT_APP_PASSWORD, 
        MICROSOFT_APP_TENANT_ID
    )

adapter = BotFrameworkAdapter(settings)

# Store conversation references (in-memory for testing)
conversation_references: dict[str, ConversationReference] = {}

async def on_turn(turn_context: TurnContext):
    conv_ref = TurnContext.get_conversation_reference(turn_context.activity)
    conversation_references[conv_ref.user.id] = conv_ref

    if turn_context.activity.type == ActivityTypes.message:
        txt = (turn_context.activity.text or "").strip()
        if txt.lower() == "hi":
            await turn_context.send_activity(
                "✅ Handshake complete. Now you can call POST /send to DM you from an API."
            )
        else:
            await turn_context.send_activity(f"✅ Received: {txt}")

@app.post("/api/messages")
async def messages(req: Request):
    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")
    await adapter.process_activity(activity, auth_header, on_turn)
    return {}

@app.post("/send")
async def send(payload: dict):
    text = payload.get("text", "hello from API")

    if not conversation_references:
        return {"ok": False, "error": "No conversation reference yet. DM the bot in Teams with 'hi' first."}

    _, conv_ref = next(iter(conversation_references.items()))

    async def _send(turn_context: TurnContext):
        await turn_context.send_activity(text)

    await adapter.continue_conversation(conv_ref, _send, MICROSOFT_APP_ID)
    return {"ok": True}
