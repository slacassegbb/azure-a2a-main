from pydantic import BaseModel, Field
from typing import Literal, Any
from uuid import uuid4

from a2a.types import (
    Message,
    Task,
    AgentCard,
)


class JSONRPCMessage(BaseModel):
    jsonrpc: Literal['2.0'] = '2.0'
    id: int | str | None = Field(default_factory=lambda: uuid4().hex)


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JSONRPCResponse(JSONRPCMessage):
    result: Any | None = None
    error: JSONRPCError | None = None


class Conversation(BaseModel):
    conversation_id: str
    is_active: bool
    name: str = ''
    task_ids: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)


class Event(BaseModel):
    id: str
    actor: str = ''
    # TODO: Extend to support internal concepts for models, like function calls.
    content: Message
    timestamp: float


class ListMessageResponse(JSONRPCResponse):
    result: list[Message] | None = None


class MessageInfo(BaseModel):
    message_id: str
    context_id: str


class SendMessageResponse(JSONRPCResponse):
    result: Message | MessageInfo | None = None


class GetEventResponse(JSONRPCResponse):
    result: list[Event] | None = None


class ListConversationResponse(JSONRPCResponse):
    result: list[Conversation] | None = None


class PendingMessageResponse(JSONRPCResponse):
    result: list[tuple[str, str]] | None = None


class CreateConversationResponse(JSONRPCResponse):
    result: Conversation | None = None


class ListTaskResponse(JSONRPCResponse):
    result: list[Task] | None = None


class RegisterAgentResponse(JSONRPCResponse):
    result: str | None = None


class ListAgentResponse(JSONRPCResponse):
    result: list[AgentCard] | None = None
