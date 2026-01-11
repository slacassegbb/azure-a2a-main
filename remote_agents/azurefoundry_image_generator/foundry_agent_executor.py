"""
AI Foundry Image Generator Agent Executor for A2A framework.
Adapted from ADK agent executor pattern to work with Azure AI Foundry agents for prompt orchestration and image generation.
"""
import asyncio
import logging
import base64
import os
import tempfile
import time
from typing import Optional, Dict, List, Any

from foundry_agent import FoundryImageGeneratorAgent

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, DataPart, FilePart, FileWithBytes, FileWithUri, Message, Part, TaskState, TextPart
from a2a.utils.message import new_agent_text_message, new_agent_parts_message

logger = logging.getLogger(__name__)
# Set to INFO to hide verbose debug logs (can be changed to DEBUG for troubleshooting)
logger.setLevel(logging.INFO)


class FoundryImageGeneratorAgentExecutor(AgentExecutor):
    """
    AgentExecutor that runs the Azure AI Foundry image generator agent for creative prompt handling.
    """

    # Class-level shared agent instance to avoid multiple agent creations
    _shared_foundry_agent: Optional[FoundryImageGeneratorAgent] = None
    _agent_lock = asyncio.Lock()
    _last_request_time: float = 0
    _min_request_interval: float = 5.0  # Increase to 5 seconds minimum between requests
    _request_semaphore = asyncio.Semaphore(1)  # Max 1 concurrent request
    _api_call_count: int = 0
    _api_call_window_start: float = 0
    _max_api_calls_per_minute: int = 15  # Much more conservative - 15 calls per minute
    _startup_complete: bool = False

    @classmethod
    async def get_shared_agent(cls) -> Optional[FoundryImageGeneratorAgent]:
        """Get the shared agent that was initialized at startup (if available)."""
        async with cls._agent_lock:
            return cls._shared_foundry_agent
    
    @classmethod
    async def initialize_at_startup(cls) -> None:
        """Initialize the shared image generator agent at startup instead of on first request."""
        async with cls._agent_lock:
            if not cls._shared_foundry_agent:
                logger.info("🚀 Initializing Foundry Image Generator agent at startup...")
                try:
                    cls._shared_foundry_agent = FoundryImageGeneratorAgent()
                    await cls._shared_foundry_agent.create_agent()
                    cls._startup_complete = True
                    logger.info("✅ Foundry Image Generator agent startup initialization completed successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize image generator agent at startup: {e}")
                    cls._shared_foundry_agent = None
                    cls._startup_complete = False
                    raise

    def __init__(self, card: AgentCard):
        self._active_threads: Dict[str, str] = {}  # context_id -> thread_id mapping
        self._waiting_for_input: Dict[str, str] = {}
        self._pending_updaters: Dict[str, TaskUpdater] = {}
        self._input_events: Dict[str, asyncio.Event] = {}
        self._last_received_files: List[Dict[str, str]] = []

    async def _get_or_create_agent(self) -> FoundryImageGeneratorAgent:
        """Get the shared Foundry Image Generator agent (with fallback to lazy creation)."""
        async with FoundryImageGeneratorAgentExecutor._agent_lock:
            if not FoundryImageGeneratorAgentExecutor._shared_foundry_agent:
                if FoundryImageGeneratorAgentExecutor._startup_complete:
                    # Startup was supposed to happen but failed
                    raise RuntimeError("Image generator agent startup initialization failed - agent not available")

                # Fallback to lazy creation if startup wasn't called
                logger.warning("⚠️ Image generator agent not initialized at startup, falling back to lazy creation...")
                FoundryImageGeneratorAgentExecutor._shared_foundry_agent = FoundryImageGeneratorAgent()
                await FoundryImageGeneratorAgentExecutor._shared_foundry_agent.create_agent()
                logger.info("Fallback image generator agent creation completed")
            return FoundryImageGeneratorAgentExecutor._shared_foundry_agent

    async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[FoundryImageGeneratorAgent] = None
    ) -> str:
        if agent is None:
            agent = await self._get_or_create_agent()
        # Reuse thread if it exists for this context_id
        if context_id in self._active_threads:
            return self._active_threads[context_id]
        # Otherwise, create a new thread and store it
        thread = await agent.create_thread()
        thread_id = thread.id
        self._active_threads[context_id] = thread_id
        return thread_id



    async def _process_request(
        self,
        message_parts: List[Part],
        context_id: str,
        task_updater: TaskUpdater,
    ) -> None:
        received_files: List[Dict[str, str]] = []
        if message_parts:
            for part in message_parts:
                if hasattr(part, "root"):
                    root_part = part.root

                    if isinstance(root_part, FilePart):
                        file_obj = root_part.file
                        if isinstance(file_obj, FileWithUri):
                            received_files.append({
                                "name": getattr(file_obj, "name", "unknown"),
                                "uri": getattr(file_obj, "uri", ""),
                                "mime": getattr(file_obj, "mimeType", ""),
                            })
                        elif isinstance(file_obj, FileWithBytes):
                            received_files.append({
                                "name": getattr(file_obj, "name", "unknown"),
                                "uri": "",
                                "mime": getattr(file_obj, "mimeType", ""),
                                "bytes": len(getattr(file_obj, "bytes", b""))
                            })

                    elif isinstance(root_part, DataPart):
                        data = getattr(root_part, "data", None)
                        if isinstance(data, dict) and data.get("artifact-uri"):
                            received_files.append({
                                "name": data.get("file-name", "unknown"),
                                "uri": data.get("artifact-uri", ""),
                                "mime": data.get("mime", ""),
                            })

        if received_files:
            self._last_received_files = received_files
            print("[Image Generator Executor] Received file references:")
            for file_meta in received_files:
                print(f"  • name={file_meta.get('name')} uri={file_meta.get('uri')} mime={file_meta.get('mime')}")
            logger.info("📎 Received file references in A2A message", extra={"files": received_files, "context_id": context_id})
        else:
            logger.info("📎 No file references received in A2A message for context %s", context_id)
        try:
            user_message, attachments = self._convert_parts_to_payload(message_parts)
            agent = await self._get_or_create_agent()
            thread_id = await self._get_or_create_thread(context_id, agent)

            attempt = 0
            while attempt < 2:
                attempt += 1

                try:
                    # Use streaming to show tool calls in real-time
                    responses: List[Any] = []
                    tools_called = []
                    seen_tools = set()

                    async for event in agent.run_conversation_stream(
                        thread_id,
                        user_message,
                        attachments=attachments,
                    ):
                        # Check if this is a tool call event from remote agent
                        if event.startswith("🛠️ Remote agent executing:"):
                            tool_description = event.replace("🛠️ Remote agent executing: ", "").strip()
                            if tool_description not in seen_tools:
                                seen_tools.add(tool_description)
                                tools_called.append(tool_description)
                                # Emit tool call in real-time
                                tool_event_msg = new_agent_text_message(
                                    f"🛠️ Remote agent executing: {tool_description}", context_id=context_id
                                )
                                await task_updater.update_status(
                                    TaskState.working,
                                    message=tool_event_msg
                                )
                        # Check if this is a processing message
                        elif event.startswith("🤖") or event.startswith("🧠") or event.startswith("🔍") or event.startswith("📝"):
                            # Emit processing message in real-time
                            processing_msg = new_agent_text_message(
                                event, context_id=context_id
                            )
                            await task_updater.update_status(
                                TaskState.working,
                                message=processing_msg
                            )
                        # Check if this is an error
                        elif event.startswith("Error:"):
                            await task_updater.failed(
                                message=new_agent_text_message(event, context_id=context_id)
                            )
                            return

                        # Otherwise, treat as a regular response (only if it's a string)
                        elif isinstance(event, str):
                            responses.append(event)

                    # Emit the final response
                    if responses:
                        artifacts = agent.pop_latest_artifacts()
                        artifact_parts = []
                        if artifacts:
                            # Convert artifacts to appropriate Part types
                            for artifact in artifacts:
                                if isinstance(artifact, dict) and artifact.get("artifact-uri"):
                                    # For artifacts with URIs (like images), create FilePart with FileWithUri
                                    file_with_uri = FileWithUri(
                                        name=artifact.get("file-name", "artifact"),
                                        uri=artifact["artifact-uri"],
                                        mimeType=artifact.get("mime", "image/png")
                                    )
                                    artifact_parts.append(Part(root=FilePart(file=file_with_uri)))
                                else:
                                    # For other artifacts, use DataPart
                                    artifact_parts.append(Part(root=DataPart(data=artifact)))
                            
                            artifact_message = new_agent_parts_message(parts=artifact_parts, context_id=context_id)
                            responses.append(artifact_message)
                            await task_updater.update_status(
                                TaskState.working,
                                message=artifact_message
                            )
                        final_text_response = next(
                            (resp for resp in reversed(responses) if isinstance(resp, str)),
                            None
                        )
                        if final_text_response is None:
                            final_text_response = "Image generated successfully."
                        
                        # Include both text summary AND artifact parts in final completion message
                        # Log a preview of the response (first 500 chars)
                        response_preview = final_text_response[:500] + "..." if len(final_text_response) > 500 else final_text_response
                        logger.info(f"📤 Agent response ({len(final_text_response)} chars, {len(artifact_parts)} artifacts): {response_preview}")
                        
                        # Emit the text response as a status update FIRST so it shows in the DAG
                        # (Similar to how branding agent sends text directly)
                        await task_updater.update_status(
                            TaskState.working,
                            message=new_agent_text_message(final_text_response, context_id=context_id)
                        )
                        
                        # This ensures downstream agents receive file metadata for agent-to-agent file exchange
                        final_parts = [Part(root=TextPart(text=final_text_response))]
                        if artifact_parts:
                            final_parts.extend(artifact_parts)
                        
                        # Add token usage if available
                        if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                            final_parts.append(Part(root=DataPart(data={
                                'type': 'token_usage',
                                **agent.last_token_usage
                            })))
                            logger.info(f"💰 Including token usage in response: {agent.last_token_usage}")
                        
                        await task_updater.complete(
                            message=new_agent_parts_message(parts=final_parts, context_id=context_id)
                        )
                    else:
                        logger.warning("⚠️ No response generated by agent")
                        
                        # Build message parts (even for error case)
                        import uuid
                        message_parts = [TextPart(text="No response generated")]
                        
                        # Add token usage even if no response (in case run consumed tokens)
                        if hasattr(agent, 'last_token_usage') and agent.last_token_usage:
                            message_parts.append(DataPart(data={
                                'type': 'token_usage',
                                **agent.last_token_usage
                            }))
                            logger.info(f"💰 Including token usage in response: {agent.last_token_usage}")
                        
                        await task_updater.complete(
                            message=Message(
                                role="agent",
                                messageId=str(uuid.uuid4()),
                                parts=message_parts,
                                contextId=context_id
                            )
                        )
                    return

                except RuntimeError as run_error:
                    error_text = str(run_error)
                    if (
                        "active Azure AI Foundry run(s)" in error_text
                        and attempt < 2
                    ):
                        logger.warning(
                            "Thread %s still has active run(s); creating a fresh thread for context %s",
                            thread_id,
                            context_id,
                        )
                        new_thread = await agent.create_thread()
                        thread_id = new_thread.id
                        self._active_threads[context_id] = thread_id
                        continue
                    raise

        except asyncio.CancelledError:
            logger.info("Request processing for context %s was cancelled", context_id)
            try:
                await task_updater.failed(
                    message=new_agent_text_message("Task cancelled", context_id=context_id)
                )
            except Exception as update_error:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to publish cancellation status for context %s: %s",
                    context_id,
                    update_error,
                )
            return

        except Exception as e:
            await task_updater.failed(
                message=new_agent_text_message(f"Error: {e}", context_id=context_id)
            )

    def _convert_parts_to_payload(self, parts: List[Part]) -> tuple[str, List[Dict[str, Any]]]:
        """Convert message parts to text prompt plus structured file attachments."""
        texts: List[str] = []
        encoded_parts: List[Dict[str, Any]] = []

        for part in parts:
            p = part.root
            if isinstance(p, TextPart):
                if p.text:
                    texts.append(p.text)
            elif isinstance(p, DataPart):
                if isinstance(p.data, dict):
                    uri = p.data.get("artifact-uri")
                    mime = p.data.get("mime") or p.data.get("media-type")
                    file_name = p.data.get("file-name") or p.data.get("artifact-id")
                    role = p.data.get("role")
                    if not role:
                        metadata = p.data.get("metadata") or {}
                        role = metadata.get("role")
                    if uri:
                        encoded_parts.append({
                            "kind": "file",
                            "file": {
                                "name": file_name,
                                "mimeType": mime or "application/octet-stream",
                                "uri": uri,
                                "size": p.data.get("file-size"),
                                "storage": p.data.get("storage-type"),
                                **({"role": role} if role else {}),
                            },
                        })
                    else:
                        encoded_parts.append({"kind": "data", "data": p.data})
                else:
                    encoded_parts.append({"kind": "data", "data": p.data})
            elif isinstance(p.file, FileWithUri):
                role_hint = getattr(p.file, "role", None)
                metadata_role = (p.metadata or {}).get("role") if getattr(p, "metadata", None) else None
                resolved_role = (role_hint or metadata_role)
                file_payload = {
                    "name": getattr(p.file, "name", "file"),
                    "mimeType": getattr(p.file, "mimeType", "application/octet-stream"),
                    "uri": p.file.uri,
                }
                if resolved_role:
                    file_payload["role"] = str(resolved_role).lower()
                if getattr(p, "metadata", None):
                    file_payload["metadata"] = {**p.metadata}

                encoded_parts.append({
                    "kind": "file",
                    "file": file_payload,
                })
            elif isinstance(p.file, FileWithBytes):
                try:
                    raw_bytes = base64.b64decode(p.file.bytes)
                except Exception:
                    raw_bytes = p.file.bytes if isinstance(p.file.bytes, (bytes, bytearray)) else None

                file_entry: Dict[str, Any] = {
                    "kind": "file",
                    "file": {
                        "name": getattr(p.file, "name", "file"),
                        "mimeType": getattr(p.file, "mimeType", "application/octet-stream"),
                        **({"role": getattr(p.file, "role", None)} if getattr(p.file, "role", None) else {}),
                    },
                }

                if raw_bytes is not None:
                    file_entry["file"]["bytes"] = raw_bytes
                else:
                    file_entry["file"]["bytes_base64"] = p.file.bytes

                encoded_parts.append(file_entry)

        prompt_text = "\n\n".join(texts).strip()

        has_base = any(
            isinstance(part, dict)
            and part.get("kind") == "file"
            and part.get("file", {}).get("role", "").lower() == "base"
            for part in encoded_parts
        )
        has_mask = any(
            isinstance(part, dict)
            and part.get("kind") == "file"
            and part.get("file", {}).get("role", "").lower() == "mask"
            for part in encoded_parts
        )

        if has_base:
            prompt_sections = [prompt_text] if prompt_text else []
            prompt_sections.append("Reuse the supplied base image exactly; do not regenerate a new subject.")
            if has_mask:
                prompt_sections.append("Apply the requested edits only inside the provided transparency mask.")
            prompt_text = "\n\n".join(section for section in prompt_sections if section).strip()

        return prompt_text, encoded_parts

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        logger.info(f"Executing request for context {context.context_id}")
        
        # CRITICAL: Apply rate limiting at the execute level to control between different user requests
        async with FoundryImageGeneratorAgentExecutor._request_semaphore:
            # Check API call rate limiting
            current_time = time.time()
            
            # Reset the window if it's been more than a minute
            if current_time - FoundryImageGeneratorAgentExecutor._api_call_window_start > 60:
                FoundryImageGeneratorAgentExecutor._api_call_count = 0
                FoundryImageGeneratorAgentExecutor._api_call_window_start = current_time
            
            # Check if we're approaching the API limit
            if FoundryImageGeneratorAgentExecutor._api_call_count >= FoundryImageGeneratorAgentExecutor._max_api_calls_per_minute:
                wait_time = 60 - (current_time - FoundryImageGeneratorAgentExecutor._api_call_window_start)
                if wait_time > 0:
                    logger.warning(f"API rate limit protection: waiting {wait_time:.1f}s to reset window")
                    await asyncio.sleep(wait_time)
                    # Reset counters
                    FoundryImageGeneratorAgentExecutor._api_call_count = 0
                    FoundryImageGeneratorAgentExecutor._api_call_window_start = time.time()
            
            # Enforce minimum interval between requests - THIS IS THE KEY FIX
            time_since_last = current_time - FoundryImageGeneratorAgentExecutor._last_request_time
            if time_since_last < FoundryImageGeneratorAgentExecutor._min_request_interval:
                sleep_time = FoundryImageGeneratorAgentExecutor._min_request_interval - time_since_last
                logger.warning(f"🚦 RATE LIMITING: Waiting {sleep_time:.2f}s between user requests (last request was {time_since_last:.2f}s ago)")
                await asyncio.sleep(sleep_time)
            
            FoundryImageGeneratorAgentExecutor._last_request_time = time.time()
            
            # Now proceed with the actual request processing
            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            if not context.current_task:
                await updater.submit()
            await updater.start_work()
            await self._process_request(
                context.message.parts if context.message else [],
                context.context_id,
                updater,
            )
            logger.info(f"Completed execution for {context.context_id}")

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        logger.info(f"Cancelling context {context.context_id}")
        if context.context_id in self._input_events:
            self._input_events[context.context_id].set()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.failed(
            message=new_agent_text_message("Task cancelled", context_id=context.context_id)
        )

    async def cleanup(self):
        self._active_threads.clear()
        self._waiting_for_input.clear()
        self._pending_updaters.clear()
        self._input_events.clear()
        logger.info("Executor cleaned up")


def create_foundry_agent_executor(card: AgentCard) -> FoundryImageGeneratorAgentExecutor:
    return FoundryImageGeneratorAgentExecutor(card)


async def initialize_foundry_image_generators_at_startup():
    """Initialize shared image generator agent resources at application startup."""
    await FoundryImageGeneratorAgentExecutor.initialize_at_startup()