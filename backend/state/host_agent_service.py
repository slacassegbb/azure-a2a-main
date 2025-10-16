import json
import os
import sys
import traceback
import uuid
from pathlib import Path

from typing import Any

from a2a.types import FileWithBytes, Message, Part, Role, Task, TaskState
from service.client.client import ConversationClient
from service.azure_eventhub_streamer import get_event_hub_streamer
from dotenv import load_dotenv


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=False)


def get_context_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get contextId from an object, trying both contextId and context_id fields.
    A2A protocol officially uses contextId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try contextId first (official A2A protocol field name)
        if hasattr(obj, 'contextId') and obj.contextId is not None:
            return obj.contextId
        # Fallback to context_id for compatibility
        if hasattr(obj, 'context_id') and obj.context_id is not None:
            return obj.context_id
        # Final fallback using getattr
        return getattr(obj, 'contextId', getattr(obj, 'context_id', default or ''))
    except Exception:
        return default or ''


def get_message_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get messageId from an object, trying both messageId and message_id fields.
    A2A protocol officially uses messageId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try messageId first (official A2A protocol field name)
        if hasattr(obj, 'messageId') and obj.messageId is not None:
            return obj.messageId
        # Fallback to message_id for compatibility
        if hasattr(obj, 'message_id') and obj.message_id is not None:
            return obj.message_id
        # Final fallback using getattr
        return getattr(obj, 'messageId', getattr(obj, 'message_id', default or str(uuid.uuid4())))
    except Exception:
        return default or str(uuid.uuid4())


def get_task_id(obj: Any, default: str = None) -> str:
    """
    Helper function to get taskId from an object, trying both taskId and task_id fields.
    A2A protocol officially uses taskId (camelCase), but this provides fallback compatibility.
    """
    try:
        # Try taskId first (official A2A protocol field name)
        if hasattr(obj, 'taskId') and obj.taskId is not None:
            return obj.taskId
        # Fallback to task_id for compatibility
        if hasattr(obj, 'task_id') and obj.task_id is not None:
            return obj.task_id
        # Final fallback using getattr
        return getattr(obj, 'taskId', getattr(obj, 'task_id', default or ''))
    except Exception:
        return default or ''


from service.types import (
    Conversation,
    CreateConversationRequest,
    Event,
    GetEventRequest,
    ListAgentRequest,
    ListConversationRequest,
    ListMessageRequest,
    ListTaskRequest,
    MessageInfo,
    PendingMessageRequest,
    RegisterAgentRequest,
    SendMessageRequest,
)

from .state import (
    AppState,
    SessionTask,
    StateConversation,
    StateEvent,
    StateMessage,
    StateTask,
)


server_url = os.environ.get('BACKEND_SERVER_URL', os.environ.get('A2A_BACKEND_URL', 'http://localhost:12000'))


async def ListConversations() -> list[Conversation]:
    client = ConversationClient(server_url)
    try:
        response = await client.list_conversation(ListConversationRequest())
        return response.result if response.result else []
    except Exception as e:
        print('Failed to list conversations: ', e)
    return []


async def SendMessage(message: Message) -> Message | MessageInfo | None:
    client = ConversationClient(server_url)
    try:
        # Stream outgoing message to Event Hub
        streamer = await get_event_hub_streamer()
        if streamer and get_context_id(message):
            await streamer.stream_message_sent(message, get_context_id(message))
        
        response = await client.send_message(SendMessageRequest(params=message))
        
        # Stream response message if available
        if response.result and streamer and get_context_id(message):
            if isinstance(response.result, Message):
                await streamer.stream_message_received(response.result, get_context_id(message))
        
        return response.result
        
        return response.result
    except Exception as e:
        traceback.print_exc()
        print('Failed to send message: ', e)
    return None


async def CreateConversation() -> Conversation:
    client = ConversationClient(server_url)
    try:
        response = await client.create_conversation(CreateConversationRequest())
        conversation = (
            response.result
            if response.result
            else Conversation(conversation_id='', is_active=False)
        )
        
        # Stream conversation creation to Event Hub
        streamer = await get_event_hub_streamer()
        if streamer and conversation.conversation_id:
            state_conversation = convert_conversation_to_state(conversation)
            await streamer.stream_conversation_created(state_conversation)
        
        return conversation
    except Exception as e:
        print('Failed to create conversation', e)
    return Conversation(conversation_id='', is_active=False)


async def ListRemoteAgents():
    client = ConversationClient(server_url)
    try:
        response = await client.list_agents(ListAgentRequest())
        return response.result
    except Exception as e:
        print('Failed to read agents', e)


async def AddRemoteAgent(path: str):
    client = ConversationClient(server_url)
    try:
        await client.register_agent(RegisterAgentRequest(params=path))
        
        # Stream agent registration to Event Hub
        streamer = await get_event_hub_streamer()
        if streamer:
            await streamer.stream_agent_registered(path)
            
    except Exception as e:
        print('Failed to register the agent', e)


async def GetEvents() -> list[Event]:
    client = ConversationClient(server_url)
    try:
        response = await client.get_events(GetEventRequest())
        return response.result if response.result else []
    except Exception as e:
        print('Failed to get events', e)
    return []


async def GetProcessingMessages():
    client = ConversationClient(server_url)
    try:
        response = await client.get_pending_messages(PendingMessageRequest())
        return dict(response.result)
    except Exception as e:
        print('Error getting pending messages', e)
        return {}


def GetMessageAliases():
    return {}


async def GetTasks():
    client = ConversationClient(server_url)
    try:
        response = await client.list_tasks(ListTaskRequest())
        return response.result
    except Exception as e:
        print('Failed to list tasks ', e)
        return []


async def ListMessages(conversation_id: str) -> list[Message]:
    """List messages for a conversation."""
    client = ConversationClient(server_url)
    try:
        response = await client.list_messages(
            ListMessageRequest(params=conversation_id)
        )
        messages = response.result if response.result else []
        return messages
    except Exception as e:
        print(f'Error listing messages for conversation {conversation_id}: {e}')
        return []


async def UpdateAppState(state: AppState, conversation_id: str):
    """Update the app state."""
    try:
        if conversation_id:
            state.current_conversation_id = conversation_id
            messages = await ListMessages(conversation_id)
            if not messages:
                state.messages = []
            else:
                state.messages = [convert_message_to_state(x) for x in messages]
        conversations = await ListConversations()
        if not conversations:
            state.conversations = []
        else:
            # Convert and stream conversation updates
            state.conversations = [
                convert_conversation_to_state(x) for x in conversations
            ]
            
            # Stream conversation updates to Event Hub
            streamer = await get_event_hub_streamer()
            if streamer:
                for conv in state.conversations:
                    await streamer.stream_conversation_updated(conv)

        # Handle tasks
        old_task_count = len(state.task_list)
        state.task_list = []
        tasks_result = await GetTasks()
        if tasks_result is None:
            tasks_result = []
        for task in tasks_result:
            session_task = SessionTask(
                context_id=extract_conversation_id(task),
                task=convert_task_to_state(task),
            )
            state.task_list.append(session_task)
        
        # Stream task updates to Event Hub
        streamer = await get_event_hub_streamer()
        if streamer and len(state.task_list) > old_task_count:
            # New tasks were added
            for session_task in state.task_list[old_task_count:]:
                await streamer.stream_task_created(session_task.task, session_task.context_id)
        
        state.background_tasks = await GetProcessingMessages()
        state.message_aliases = GetMessageAliases()
        
        # Stream events to Event Hub
        if streamer:
            events = await GetEvents()
            for event in events:
                state_event = convert_event_to_state(event)
                await streamer.stream_event_occurred(state_event)
                
    except Exception as e:
        print('Failed to update state: ', e)
        traceback.print_exc(file=sys.stdout)


async def UpdateApiKey(api_key: str):
    """Update the API key"""
    import httpx

    success = False
    try:
        # Set the environment variable
        os.environ['GOOGLE_API_KEY'] = api_key

        # Call the update API endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f'{server_url}/api_key/update', json={'api_key': api_key}
            )
            response.raise_for_status()
        success = True
    except Exception as e:
        print('Failed to update API key: ', e)
    
    # Stream API key update event to Event Hub
    streamer = await get_event_hub_streamer()
    if streamer:
        await streamer.stream_api_key_updated(success)
    
    return success


def convert_message_to_state(message: Message) -> StateMessage:
    if not message:
        return StateMessage()

    return StateMessage(
        message_id=get_message_id(message),
        context_id=get_context_id(message) if get_context_id(message) else '',
        task_id=get_task_id(message) if get_task_id(message) else '',
        role=str(message.role),
        content=extract_content(message.parts),
    )


def convert_conversation_to_state(
    conversation: Conversation,
) -> StateConversation:
    return StateConversation(
        conversation_id=conversation.conversation_id,
        conversation_name=conversation.name,
        is_active=conversation.is_active,
        message_ids=[extract_message_id(x) for x in conversation.messages],
    )


def convert_task_to_state(task: Task) -> StateTask:
    # Get the first message as the description
    output = (
        [extract_content(a.parts) for a in task.artifacts]
        if task.artifacts
        else []
    )
    if not task.history:
        return StateTask(
            task_id=task.id,
            context_id=get_context_id(task),
            state=TaskState.failed.name,
            message=StateMessage(
                message_id=str(uuid.uuid4()),
                context_id=get_context_id(task),
                task_id=task.id,
                role=Role.agent.name,
                content=[('No history', 'text')],
            ),
            artifacts=output,
        )
    else:
        message = task.history[0]
        last_message = task.history[-1]
        if last_message != message:
            output = [extract_content(last_message.parts)] + output
    return StateTask(
        task_id=task.id,
        context_id=get_context_id(task),
        state=str(task.status.state),
        message=convert_message_to_state(message),
        artifacts=output,
    )


def convert_event_to_state(event: Event) -> StateEvent:
    return StateEvent(
        context_id=extract_message_conversation(event.content),
        actor=event.actor,
        role=event.content.role.name,
        id=event.id,
        content=extract_content(event.content.parts),
    )


def extract_content(
    message_parts: list[Part],
) -> list[tuple[str | dict[str, Any], str]]:
    parts: list[tuple[str | dict[str, Any], str]] = []
    if not message_parts:
        return []
    for part in message_parts:
        p = part.root
        if p.kind == 'text':
            parts.append((p.text, 'text/plain'))
        elif p.kind == 'file':
            if isinstance(p.file, FileWithBytes):
                # Don't display raw base64 - show file info instead
                file_name = getattr(p.file, 'name', 'unknown_file')
                file_size = len(p.file.bytes) if isinstance(p.file.bytes, str) else len(str(p.file.bytes))
                mime_type = p.file.mimeType or 'unknown'
                file_display = f"📎 File: {file_name} ({file_size} chars, {mime_type})"
                parts.append((file_display, 'text/plain'))
            else:
                parts.append((p.file.uri, p.file.mimeType or ''))
        elif p.kind == 'data':
            try:
                jsonData = json.dumps(p.data)
                if 'type' in p.data and p.data['type'] == 'form':
                    parts.append((p.data, 'form'))
                else:
                    parts.append((jsonData, 'application/json'))
            except Exception as e:
                print('Failed to dump data', e)
                parts.append(('<data>', 'text/plain'))
    return parts


def extract_message_id(message: Message) -> str:
    return message.messageId


def extract_message_conversation(message: Message) -> str:
    return get_context_id(message) if get_context_id(message) else ''


def extract_conversation_id(task: Task) -> str:
    if get_context_id(task):
        return get_context_id(task)
    # Tries to find the first conversation id for the message in the task.
    if task.status.message:
        return get_context_id(task.status.message) or ''
    return ''
