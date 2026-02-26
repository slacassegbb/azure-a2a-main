"""
WorkflowOrchestration - Workflow execution and agent mode orchestration for FoundryHostAgent2.

This module contains methods related to:
- Parsed workflow execution (parallel and sequential)
- Agent mode orchestration loop
- Task execution with state management
- Workflow step processing
- Artifact collection

These are extracted from foundry_agent_a2a.py to improve code organization.
The class is designed to be used as a mixin with FoundryHostAgent2.
"""

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# Import logging utilities
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from a2a.types import Task, DataPart

from log_config import (
    log_debug,
    log_error,
    log_info,
    log_warning,
)

from ..models import (
    SessionContext,
    AgentModeTask,
    AgentModePlan,
    NextStep,
    RouteSelection,
    EvaluationResult,
    QueryResult,
)
from ..tool_context import DummyToolContext
from ..foundry_agent_a2a import _current_parallel_call_id


class WorkflowOrchestration:
    """
    Mixin providing workflow execution and agent mode orchestration methods.
    
    This mixin handles:
    - Parsed workflow execution (parallel and sequential)
    - Agent mode orchestration loop with LLM planning
    - Task execution with state management
    - HITL (human-in-the-loop) support
    - Artifact collection and context passing
    
    Expected instance attributes (set by main class):
    - self.cards: Dict of agent cards
    - self._azure_blob_client: Azure blob client
    - self._active_conversations: Dict for conversation tracking
    - self.host_token_usage: Dict for token tracking
    
    Expected methods from other mixins:
    - self._emit_status_event()
    - self._emit_granular_agent_event()
    - self._extract_text_from_response()
    - self.send_message()
    - self._select_agent_for_task()
    - self._call_azure_openai_structured()
    """

    def _build_interrupted_goal(self, original_goal: str, interrupt_instruction: str,
                                 completed_tasks: list) -> str:
        """Build an updated goal string that appends the interrupt instruction
        to the original goal, preserving context about completed work."""
        completed_summary = "\n".join([
            f"- [DONE] {t.task_description[:100]} (by {t.recommended_agent})"
            for t in completed_tasks if t.state == "completed"
        ]) or "- (none yet)"
        return (
            f"{original_goal}\n\n"
            f"ADDITIONALLY: {interrupt_instruction}\n\n"
            f"The following steps were already completed:\n{completed_summary}\n\n"
            f"INSTRUCTION: Continue working on the original goal AND the additional instruction above. "
            f"Do NOT repeat completed tasks."
        )

    async def _load_agent_from_catalog(self, agent_name: str) -> bool:
        """
        Load an agent from the global catalog and register it for this session.
        
        This enables workflows and scheduled workflows to call agents that aren't
        explicitly registered to the session. The agent just needs to exist in
        the catalog (database).
        
        Args:
            agent_name: Name of the agent to load
            
        Returns:
            True if agent was loaded successfully, False if not found
        """
        try:
            from service.agent_registry import get_registry
            from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider
            
            registry = get_registry()
            agent_config = registry.get_agent(agent_name)
            
            if not agent_config:
                log_debug(f"[CATALOG_FALLBACK] Agent '{agent_name}' not found in catalog")
                return False
            
            log_debug(f"[CATALOG_FALLBACK] Found agent '{agent_name}' in catalog: {agent_config.get('url')}")
            
            # Build AgentCard from catalog data
            skills = []
            if agent_config.get('skills'):
                for skill in agent_config['skills']:
                    if isinstance(skill, dict):
                        skills.append(AgentSkill(
                            id=skill.get('id', skill.get('name', '')),
                            name=skill.get('name', ''),
                            description=skill.get('description', ''),
                            tags=skill.get('tags', [])
                        ))
            
            caps_data = agent_config.get('capabilities', {})
            if isinstance(caps_data, dict):
                capabilities = AgentCapabilities(
                    streaming=caps_data.get('streaming', False),
                    pushNotifications=caps_data.get('pushNotifications', False)
                )
            else:
                capabilities = AgentCapabilities(streaming=False, pushNotifications=False)
            
            provider = None
            if agent_config.get('provider'):
                prov_data = agent_config['provider']
                if isinstance(prov_data, dict):
                    provider = AgentProvider(organization=prov_data.get('organization', ''))
            
            card = AgentCard(
                name=agent_config['name'],
                url=agent_config['url'],
                description=agent_config.get('description', ''),
                version=agent_config.get('version') or '1.0.0',
                skills=skills if skills else [],
                capabilities=capabilities,
                provider=provider,
                defaultInputModes=agent_config.get('defaultInputModes') or ['text'],
                defaultOutputModes=agent_config.get('defaultOutputModes') or ['text']
            )
            
            # Register the agent card (this adds to self.cards and self.remote_agent_connections)
            self.register_agent_card(card)
            
            log_debug(f"[CATALOG_FALLBACK] Registered agent '{agent_name}' from catalog")
            return True
            
        except Exception as e:
            log_error(f"[CATALOG_FALLBACK] Error loading agent '{agent_name}': {e}")
            return False

    def _deduplicate_workflow_files(self, session_context: SessionContext) -> None:
        """Deduplicate files for multi-step workflows to prevent context explosion."""
        if not hasattr(session_context, '_latest_processed_parts'):
            return
        if len(session_context._latest_processed_parts) <= 1:
            return
            
        from collections import defaultdict
        
        MAX_GENERATED_FILES = 3
        editing_roles = {}
        generated_artifacts = []
        
        for part in reversed(session_context._latest_processed_parts):
            role = None
            if isinstance(part, DataPart) and isinstance(part.data, dict):
                role = part.data.get('role')
            elif hasattr(part, 'root') and isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                role = part.root.data.get('role')
            
            if role in ['base', 'mask', 'overlay']:
                if role not in editing_roles:
                    editing_roles[role] = part
            else:
                if len(generated_artifacts) < MAX_GENERATED_FILES:
                    generated_artifacts.append(part)
        
        session_context._latest_processed_parts = list(editing_roles.values()) + generated_artifacts
    
    def _extract_file_uris_from_parts(self, parts: List[Any]) -> List[str]:
        """Extract file URIs from A2A parts for explicit file routing.
        
        This enables workflow orchestration to use the same explicit file routing
        as agent mode, preventing race conditions during parallel execution.
        
        Args:
            parts: List of A2A Part objects that may contain file URIs
            
        Returns:
            List of file URI strings
        """
        file_uris = []
        
        for part in parts:
            try:
                # Handle Part wrapper objects
                if hasattr(part, 'root'):
                    inner_part = part.root
                else:
                    inner_part = part
                
                # Extract URI from FilePart
                if hasattr(inner_part, 'file'):
                    file_obj = inner_part.file
                    if hasattr(file_obj, 'uri') and file_obj.uri:
                        file_uris.append(file_obj.uri)
                        log_debug(f"  Extracted URI: {file_obj.uri}")
                    elif hasattr(file_obj, 'url') and file_obj.url:
                        file_uris.append(file_obj.url)
                        log_debug(f"  Extracted URL: {file_obj.url}")
                
                # Handle dict format (sometimes used internally)
                elif isinstance(inner_part, dict):
                    if inner_part.get('kind') == 'file':
                        file_data = inner_part.get('file', {})
                        if 'uri' in file_data:
                            file_uris.append(file_data['uri'])
                            log_debug(f"  Extracted URI from dict: {file_data['uri']}")
            
            except Exception as e:
                log_error(f"Error extracting URI from part: {e}")
                continue
        
        return file_uris
    
    def _collect_artifacts(self, artifacts: list, session_context: SessionContext) -> List[str]:
        """Collect artifacts from response and add to session context. Returns descriptions."""
        artifact_descriptions = []
        
        if not hasattr(session_context, '_latest_processed_parts'):
            session_context._latest_processed_parts = []
        
        for artifact in artifacts:
            if not hasattr(artifact, 'parts'):
                continue
            for part in artifact.parts:
                session_context._latest_processed_parts.append(part)
                
                if hasattr(part, 'root'):
                    if hasattr(part.root, 'file'):
                        file_name = getattr(part.root.file, 'name', 'unknown')
                        artifact_descriptions.append(f"[File: {file_name}]")
                    elif hasattr(part.root, 'text'):
                        artifact_descriptions.append(part.root.text)
        
        return artifact_descriptions

    async def _emit_file_events_from_artifacts(self, artifacts: list, agent_name: str, context_id: str):
        """Emit file_uploaded WebSocket events for media artifacts (images/videos) only.

        Document files (.docx, .xlsx, .pptx) already get their events emitted through
        the SSE streaming callback during intermediate 'working' status updates.
        Image/video files are only present in the final 'completed' artifacts, which
        the streaming callback skips — so we emit them here.
        """
        _video_exts = {'mp4', 'webm', 'mov', 'avi'}
        _image_exts = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'}

        for artifact in artifacts:
            if not hasattr(artifact, 'parts'):
                continue
            for part in artifact.parts:
                if not hasattr(part, 'root'):
                    continue
                file_uri = None
                file_name = None
                content_type = None
                # DataPart with artifact-uri (image generator style)
                if hasattr(part.root, 'data') and isinstance(part.root.data, dict):
                    file_uri = part.root.data.get('artifact-uri')
                    file_name = part.root.data.get('file-name', 'artifact')
                    content_type = part.root.data.get('media-type') or part.root.data.get('mime')
                # FilePart with uri (standard A2A file)
                elif hasattr(part.root, 'file'):
                    file_obj = part.root.file
                    file_uri = getattr(file_obj, 'uri', None) or getattr(file_obj, 'url', None)
                    file_name = getattr(file_obj, 'name', 'artifact')
                    content_type = getattr(file_obj, 'mimeType', None)

                if not file_uri or not str(file_uri).startswith(('http://', 'https://')):
                    continue

                # Determine content type from extension if not set
                if not content_type:
                    ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
                    if ext in _video_exts:
                        content_type = f'video/{ext}'
                    elif ext in _image_exts:
                        content_type = f'image/{"jpeg" if ext == "jpg" else ext}'

                # Only emit for media files — documents are already handled by streaming callback
                if content_type and (content_type.startswith('image/') or content_type.startswith('video/')):
                    await self._emit_file_artifact_event(
                        filename=file_name,
                        uri=str(file_uri),
                        context_id=context_id,
                        agent_name=agent_name,
                        content_type=content_type,
                    )

    async def _emit_file_events_from_parts(self, session_context, agent_name: str, context_id: str):
        """Emit file_uploaded events from _latest_processed_parts for the current agent."""
        if not hasattr(session_context, '_latest_processed_parts'):
            return
        for part in session_context._latest_processed_parts:
            if not hasattr(part, 'root'):
                continue
            if hasattr(part.root, 'file'):
                file_obj = part.root.file
                file_uri = getattr(file_obj, 'uri', None) or getattr(file_obj, 'url', None)
                file_name = getattr(file_obj, 'name', 'artifact')
                content_type = getattr(file_obj, 'mimeType', None)
                if file_uri and str(file_uri).startswith(('http://', 'https://')):
                    if not content_type:
                        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
                        video_exts = {'mp4', 'webm', 'mov', 'avi'}
                        image_exts = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'}
                        if ext in video_exts:
                            content_type = f'video/{ext}'
                        elif ext in image_exts:
                            content_type = f'image/{"jpeg" if ext == "jpg" else ext}'
                        else:
                            continue  # Skip non-media files
                    if not content_type.startswith(('image/', 'video/')):
                        continue  # Only emit events for media files
                    await self._emit_file_artifact_event(
                        filename=file_name,
                        uri=str(file_uri),
                        context_id=context_id,
                        agent_name=agent_name,
                        content_type=content_type,
                    )

    async def _execute_evaluation_step(
        self,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        previous_task_outputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute an evaluation step using the host orchestrator LLM.

        Instead of calling a remote agent, this evaluates a condition against
        previous workflow outputs and returns a true/false result for branching.
        """
        task_desc = task.task_description
        # Strip [Step X] prefix for the evaluation prompt (don't confuse the LLM)
        criteria = re.sub(r'^\[Step\s+\d+[a-z]?\]\s*', '', task_desc)
        log_info(f"[EVALUATE] Evaluating condition: {criteria[:100]}")

        # Emit events under "Evaluate" agent name so the frontend renders
        # an agent card (not hidden in the orchestrator section)
        eval_agent_name = "Evaluate"

        await self._emit_granular_agent_event(
            eval_agent_name, f"Starting task: {task_desc[:80]}...", context_id,
            event_type="agent_start", metadata={"evaluation": True, "task_description": task_desc}
        )

        # Build context from previous step outputs AND extracted documents
        context_parts = []
        found_document = False

        # Primary source: check session_context for recently extracted documents.
        # These are stored immediately after document processing completes,
        # bypassing Azure Search indexing latency.
        extracted_docs = getattr(session_context, '_extracted_documents', [])
        if extracted_docs:
            for doc_content in extracted_docs:
                log_info(f"[EVALUATE] Using session-cached document content: {len(doc_content)} chars")
                context_parts.append(f"[Extracted Document]\n{doc_content}")
                found_document = True

        # Fallback: search Azure Search memory for extracted document content.
        # This covers cases where documents were extracted in a previous session
        # or the session_context cache was cleared.
        if not found_document:
            try:
                memory_results = await self._search_relevant_memory(
                    query=criteria,
                    context_id=session_context.contextId,
                    agent_name=None,
                    top_k=5
                )
                if memory_results:
                    for result in memory_results:
                        agent_name = result.get('agent_name', '')
                        if agent_name == 'DocumentProcessor':
                            inbound = result.get('inbound_payload', {})
                            if isinstance(inbound, str):
                                try:
                                    inbound = json.loads(inbound)
                                except Exception:
                                    pass
                            if isinstance(inbound, dict) and 'content' in inbound:
                                doc_content = str(inbound['content'])
                                log_info(f"[EVALUATE] Found document content from memory: {len(doc_content)} chars")
                                context_parts.append(f"[Extracted Document]\n{doc_content}")
                                found_document = True
                                break
            except Exception as e:
                log_error(f"[EVALUATE] Error searching memory for document content: {e}")

        # Add previous task outputs
        if previous_task_outputs:
            for output in previous_task_outputs[-3:]:
                context_parts.append(output)

        context_text = "\n\n".join(context_parts)
        if len(context_text) > 6000:
            context_text = context_text[:6000] + "... [truncated]"

        system_prompt = """You are evaluating a condition as part of a multi-agent workflow.
Based on the context from previous workflow steps, determine whether the condition is TRUE or FALSE.
Be precise and objective. Only evaluate what is asked — do not infer beyond the available data."""

        user_prompt = f"""### CONDITION TO EVALUATE
{criteria}

### CONTEXT FROM PREVIOUS WORKFLOW STEPS
{context_text if context_text else "(no previous output available)"}

Evaluate the condition and return your result."""

        try:
            eval_result = await self._call_azure_openai_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=EvaluationResult,
                context_id=context_id
            )

            result_str = "TRUE" if eval_result.result else "FALSE"
            log_info(f"[EVALUATE] Result: {result_str} — {eval_result.reasoning}")

            # Update task state
            # IMPORTANT: task.output["result"] must be a string so that the HITL
            # resume path can safely iterate previous outputs as strings.
            task.state = "completed"
            task.output = {
                "result": f"{'TRUE' if eval_result.result else 'FALSE'}: {eval_result.reasoning}",
                "reasoning": eval_result.reasoning,
                "evaluation": True
            }
            task.updated_at = datetime.now(timezone.utc)

            # Emit result to frontend as agent output (visible in agent card)
            display_text = f"Result: {result_str}\n{eval_result.reasoning}"
            await self._emit_granular_agent_event(
                eval_agent_name, display_text, context_id,
                event_type="agent_output",
                metadata={"evaluation": True, "result": eval_result.result}
            )

            # Emit agent_complete so the card shows as done
            await self._emit_granular_agent_event(
                eval_agent_name, f"{eval_agent_name} completed", context_id,
                event_type="agent_complete"
            )

            # Return output as text so the orchestrator can read it in plan history
            output_text = json.dumps({
                "result": eval_result.result,
                "reasoning": eval_result.reasoning
            })
            return {"output": output_text, "hitl_pause": False}

        except Exception as e:
            log_error(f"[EVALUATE] Error during evaluation: {e}")
            task.state = "failed"
            task.error_message = f"Evaluation failed: {str(e)}"
            task.updated_at = datetime.now(timezone.utc)
            await self._emit_granular_agent_event(
                eval_agent_name, f"Error: {str(e)[:200]}", context_id,
                event_type="agent_error", metadata={"error": str(e)[:500]}
            )
            return {"error": task.error_message, "output": None}

    async def _execute_query_step(
        self,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        previous_task_outputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a query step using the host orchestrator LLM.

        Instead of calling a remote agent, this analyzes previous workflow outputs
        and returns a structured JSON envelope with the query result.
        """
        task_desc = task.task_description
        # Strip [Step X] prefix for the query prompt
        user_query = re.sub(r'^\[Step\s+\d+[a-z]?\]\s*', '', task_desc)
        log_info(f"[QUERY] Executing query: {user_query[:100]}")

        # Emit events under "Query" agent name so the frontend renders an agent card
        query_agent_name = "Query"

        await self._emit_granular_agent_event(
            query_agent_name, f"Starting task: {task_desc[:80]}...", context_id,
            event_type="agent_start", metadata={"query": True, "task_description": task_desc}
        )

        # Build context from previous step outputs AND extracted documents
        # (same context-gathering logic as _execute_evaluation_step)
        context_parts = []
        found_document = False

        # Primary source: session-cached extracted documents
        extracted_docs = getattr(session_context, '_extracted_documents', [])
        if extracted_docs:
            for doc_content in extracted_docs:
                log_info(f"[QUERY] Using session-cached document content: {len(doc_content)} chars")
                context_parts.append(f"[Extracted Document]\n{doc_content}")
                found_document = True

        # Fallback: search Azure Search memory for extracted document content
        if not found_document:
            try:
                memory_results = await self._search_relevant_memory(
                    query=user_query,
                    context_id=session_context.contextId,
                    agent_name=None,
                    top_k=5
                )
                if memory_results:
                    for result in memory_results:
                        agent_name = result.get('agent_name', '')
                        if agent_name == 'DocumentProcessor':
                            inbound = result.get('inbound_payload', {})
                            if isinstance(inbound, str):
                                try:
                                    inbound = json.loads(inbound)
                                except Exception:
                                    pass
                            if isinstance(inbound, dict) and 'content' in inbound:
                                doc_content = str(inbound['content'])
                                log_info(f"[QUERY] Found document content from memory: {len(doc_content)} chars")
                                context_parts.append(f"[Extracted Document]\n{doc_content}")
                                found_document = True
                                break
            except Exception as e:
                log_error(f"[QUERY] Error searching memory for document content: {e}")

        # Add previous task outputs (more generous than EVALUATE since queries need more context)
        if previous_task_outputs:
            log_info(f"[QUERY] Received {len(previous_task_outputs)} previous outputs")
            for i, output in enumerate(previous_task_outputs[-5:]):
                log_info(f"[QUERY] Output {i}: {len(output)} chars, preview: {output[:100]}...")
                context_parts.append(output)
        else:
            log_warning(f"[QUERY] No previous_task_outputs received!")

        context_text = "\n\n".join(context_parts)
        log_info(f"[QUERY] Total context: {len(context_text)} chars, parts: {len(context_parts)}")
        if len(context_text) > 8000:
            context_text = context_text[:8000] + "... [truncated]"

        system_prompt = """You are analyzing data as part of a multi-agent workflow.
Based on the context from previous workflow steps, answer the query with structured results.
IMPORTANT: Always provide your best analysis using whatever data IS available. Set "ok" to true and put your full answer in the "result" field as a JSON string. Only set "ok" to false if there is literally zero relevant context. Lower your confidence score if data is partial, but still give a concrete answer."""

        user_prompt = f"""### QUERY
{user_query}

### CONTEXT FROM PREVIOUS WORKFLOW STEPS
{context_text if context_text else "(no previous output available)"}

Analyze the context and return your structured result."""

        try:
            query_result = await self._call_azure_openai_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=QueryResult,
                context_id=context_id
            )

            log_info(f"[QUERY] Result: ok={query_result.ok}, task={query_result.task}, confidence={query_result.confidence}")

            # Parse JSON strings back into dicts for the output envelope
            try:
                parsed_result = json.loads(query_result.result) if query_result.result else {}
            except (json.JSONDecodeError, TypeError):
                parsed_result = {"raw": query_result.result}
            try:
                parsed_refs = json.loads(query_result.refs) if query_result.refs else {}
            except (json.JSONDecodeError, TypeError):
                parsed_refs = {}

            # Build clean output dict with parsed JSON
            result_dict = {
                "ok": query_result.ok,
                "task": query_result.task,
                "result": parsed_result,
                "confidence": query_result.confidence,
                "notes": query_result.notes,
                "refs": parsed_refs,
            }

            # Serialize to JSON text FIRST — this is the canonical string representation
            # used for both task.output["result"] and the return value.
            # IMPORTANT: task.output["result"] must always be a string so that the
            # HITL resume path (which reads task.output.get("result")) can safely
            # iterate over previous outputs as strings (e.g., call .lower()).
            output_text = json.dumps(result_dict)

            # Update task state
            task.state = "completed"
            task.output = {"result": output_text, "query": True}
            task.updated_at = datetime.now(timezone.utc)

            # Emit result to frontend as agent output
            display_text = json.dumps(result_dict, indent=2)
            await self._emit_granular_agent_event(
                query_agent_name, display_text, context_id,
                event_type="agent_output",
                metadata={"query": True, "ok": query_result.ok, "confidence": query_result.confidence}
            )

            # Emit agent_complete
            await self._emit_granular_agent_event(
                query_agent_name, f"{query_agent_name} completed", context_id,
                event_type="agent_complete"
            )

            return {"output": output_text, "hitl_pause": False}

        except Exception as e:
            log_error(f"[QUERY] Error during query: {e}")
            task.state = "failed"
            task.error_message = f"Query failed: {str(e)}"
            task.updated_at = datetime.now(timezone.utc)
            await self._emit_granular_agent_event(
                query_agent_name, f"Error: {str(e)[:200]}", context_id,
                event_type="agent_error", metadata={"error": str(e)[:500]}
            )
            return {"error": task.error_message, "output": None}

    async def _execute_web_search_step(
        self,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        previous_task_outputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a web search step using an isolated Responses API call with BingGroundingAgentTool.

        This does NOT use _create_response_with_streaming — it makes a single non-streaming
        responses.create() call with ONLY the Bing tool. No response_id tracking, no orchestrator
        tools exposed, no streaming side effects.
        """
        task_desc = task.task_description
        user_query = re.sub(r'^\[Step\s+\d+[a-z]?\]\s*', '', task_desc)
        log_info(f"[WEB_SEARCH] Executing web search: {user_query[:100]}")

        web_search_agent_name = "Web Search"

        await self._emit_granular_agent_event(
            web_search_agent_name, f"Starting task: {task_desc[:80]}...", context_id,
            event_type="agent_start", metadata={"web_search": True, "task_description": task_desc}
        )

        # Build context from previous step outputs (last 3 for relevance)
        context_parts = []
        if previous_task_outputs:
            for output in previous_task_outputs[-3:]:
                context_parts.append(output)
        context_text = "\n\n".join(context_parts)
        if len(context_text) > 4000:
            context_text = context_text[:4000] + "... [truncated]"

        try:
            # Ensure Azure client is ready
            await self._ensure_project_client()

            # Get Bing connection ID
            bing_conn_id = getattr(self, 'bing_connection_id', None) or os.environ.get("BING_CONNECTION_ID")
            if not bing_conn_id:
                raise ValueError("BING_CONNECTION_ID not configured — web search is unavailable")

            # Use native web_search_preview tool (works on direct Foundry endpoint)
            bing_tool = {"type": "web_search_preview"}

            # Build the search prompt
            search_input = f"Search the web for: {user_query}"
            if context_text:
                search_input += f"\n\nContext from previous workflow steps:\n{context_text}"

            search_instructions = (
                "You are a web search assistant. Use the Bing search tool to find current, "
                "accurate information. Return a clear, factual summary of what you found. "
                "Include specific numbers, dates, and sources when available."
            )

            # Isolated, non-streaming responses.create() — no response_id, no orchestrator tools
            log_info(f"[WEB_SEARCH] Calling responses.create() with bing_grounding tool")
            response = await self.openai_client.responses.create(
                input=search_input,
                instructions=search_instructions,
                model=self.model_name,
                tools=[bing_tool],
            )

            # Extract text from response — guard against None at every level
            result_text = ""
            log_info(f"[WEB_SEARCH] Response type: {type(response).__name__}, has output: {hasattr(response, 'output')}")
            output_items = getattr(response, 'output', None) or []
            for item in output_items:
                content_list = getattr(item, 'content', None) or []
                for content in content_list:
                    text = getattr(content, 'text', None)
                    if text:
                        result_text += text

            # Fallback: some SDK versions expose output_text directly
            if not result_text.strip():
                output_text_attr = getattr(response, 'output_text', None)
                if output_text_attr:
                    result_text = output_text_attr
                    log_info(f"[WEB_SEARCH] Used output_text fallback: {len(result_text)} chars")

            if not result_text.strip():
                # Log response structure for debugging
                log_info(f"[WEB_SEARCH] Empty response. output_items={len(output_items)}, response attrs={[a for a in dir(response) if not a.startswith('_')]}")
                result_text = "Web search returned no results."

            log_info(f"[WEB_SEARCH] Got {len(result_text)} chars from web search")

            # Track token usage (Responses API uses input_tokens/output_tokens)
            if hasattr(response, 'usage') and response.usage:
                input_tokens = getattr(response.usage, 'input_tokens', 0)
                output_tokens = getattr(response.usage, 'output_tokens', 0)
                log_info(f"[WEB_SEARCH] Tokens: input={input_tokens}, output={output_tokens}")

            # Update task state
            task.state = "completed"
            task.output = {"web_search": True, "result": result_text}
            task.updated_at = datetime.now(timezone.utc)

            # Emit result to frontend
            await self._emit_granular_agent_event(
                web_search_agent_name, result_text, context_id,
                event_type="agent_output",
                metadata={"web_search": True}
            )

            await self._emit_granular_agent_event(
                web_search_agent_name, f"{web_search_agent_name} completed", context_id,
                event_type="agent_complete"
            )

            return {"output": result_text, "hitl_pause": False}

        except Exception as e:
            log_error(f"[WEB_SEARCH] Error during web search: {e}")
            task.state = "failed"
            task.error_message = f"Web search failed: {str(e)}"
            task.updated_at = datetime.now(timezone.utc)
            await self._emit_granular_agent_event(
                web_search_agent_name, f"Error: {str(e)[:200]}", context_id,
                event_type="agent_error", metadata={"error": str(e)[:500]}
            )
            return {"error": task.error_message, "output": None}

    async def _execute_orchestrated_task(
        self,
        task: AgentModeTask,
        session_context: SessionContext,
        context_id: str,
        workflow: Optional[str],
        user_message: str,
        extract_text_fn: Callable,
        previous_task_outputs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a single orchestrated task with full state management.
        
        This method handles:
        - File deduplication for multi-step workflows
        - Agent calling via send_message
        - HITL (input_required) detection
        - Response parsing (A2A Task or legacy format)
        - Artifact collection
        - State updates on the AgentModeTask
        
        Args:
            task: The AgentModeTask to execute
            session_context: Session state
            context_id: Conversation identifier  
            workflow: Optional workflow definition
            user_message: Original user message
            extract_text_fn: Function to extract text from responses
            
        Returns:
            Dict with output, hitl_pause flag, and error info
        """
        recommended_agent = task.recommended_agent
        task_desc = task.task_description

        log_debug(f"[Agent Mode] Executing task: {task_desc[:50]}...")

        # Detect evaluation steps — handled by host LLM, not a remote agent
        if recommended_agent and recommended_agent.upper() == "EVALUATE":
            return await self._execute_evaluation_step(
                task, session_context, context_id, previous_task_outputs
            )

        # Detect query steps — handled by host LLM, not a remote agent
        if recommended_agent and recommended_agent.upper() == "QUERY":
            return await self._execute_query_step(
                task, session_context, context_id, previous_task_outputs
            )

        # Detect web search steps — handled by host with BingGroundingAgentTool
        if recommended_agent and recommended_agent.upper() == "WEB_SEARCH":
            return await self._execute_web_search_step(
                task, session_context, context_id, previous_task_outputs
            )

        # Stream task creation event (agent_start already emitted from orchestration loop)

        # If agent not in session, try to load from global catalog
        # This enables workflows/scheduled workflows to use any cataloged agent
        if recommended_agent and recommended_agent not in self.cards:
            log_debug(f"[Agent Mode] Agent '{recommended_agent}' not in session, checking catalog...")
            agent_loaded = await self._load_agent_from_catalog(recommended_agent)
            if agent_loaded:
                log_debug(f"[Agent Mode] Loaded agent '{recommended_agent}' from catalog")
        
        if not recommended_agent or recommended_agent not in self.cards:
            available_agent_names = list(self.cards.keys()) if self.cards else []
            task.state = "failed"
            task.error_message = f"Agent '{recommended_agent}' not found. Available agents: {available_agent_names}"
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Agent Mode] Agent not found: {recommended_agent}. Available: {available_agent_names}")
            log_debug(f"[AGENT NOT FOUND] Requested: '{recommended_agent}', Available: {available_agent_names}")
            return {"error": task.error_message, "output": None}
        
        log_debug(f"[Agent Mode] Calling agent: {recommended_agent}")
        await self._emit_granular_agent_event(
            recommended_agent, f"Starting task: {task_desc[:80]}...", context_id,
            event_type="agent_start", metadata={"task_description": task_desc}
        )
        
        # Build enhanced task message with previous task output for sequential context
        # This enables agents to build upon previous work in the workflow
        enhanced_task_message = task_desc
        
        # SMART CONTEXT SELECTION: Find the most substantial previous output
        # HITL steps often return short responses like "approve", so we need to find
        # the actual data (like invoice details) from earlier steps

        # IMPORTANT: Also search Azure Search memory for DocumentProcessor content
        # The memory search may have the original document content (e.g., full invoice)
        # while previous_task_outputs only has agent summaries (e.g., Teams message)
        document_content = None
        try:
            memory_results = await self._search_relevant_memory(
                query=task_desc,
                context_id=session_context.contextId,
                agent_name=None,
                top_k=5
            )

            # Look for DocumentProcessor results with full document content
            if memory_results:
                for result in memory_results:
                    agent_name = result.get('agent_name', '')
                    if agent_name == 'DocumentProcessor':
                        inbound = result.get('inbound_payload', {})
                        if isinstance(inbound, str):
                            try:
                                import json
                                inbound = json.loads(inbound)
                            except:
                                pass
                        if isinstance(inbound, dict) and 'content' in inbound:
                            document_content = str(inbound['content'])
                            log_debug(f"[Agent Mode] Found DocumentProcessor content: {len(document_content)} chars")
                            break
        except Exception as e:
            log_error(f"[Agent Mode] Error searching memory for document content: {e}")

        if previous_task_outputs and len(previous_task_outputs) > 0:
            log_info(f"[Agent Mode] SMART CONTEXT for '{recommended_agent}': {len(previous_task_outputs)} previous outputs, memory doc={'found ' + str(len(document_content)) + ' chars' if document_content else 'none'}")

            # Include ALL previous outputs so the agent has complete context
            # (e.g., RFP extraction + web research + strategy — not just the longest one)
            max_context_chars = 50000
            context_parts = []
            total_chars = 0

            # If we have DocumentProcessor content, include it first (original document data)
            if document_content:
                context_parts.append(f"### Extracted Document Content:\n{document_content}")
                total_chars += len(document_content)

            # Strip blob URLs and local paths from previous outputs before passing as context.
            # Agents see these URLs and try to download/open files they can't process
            # (e.g., Excel agent trying to open a .docx blob URL from Word agent output).
            import re
            _url_pattern = re.compile(r'\n*File:.*?\(https?://[^\)]+\)\s*$', re.MULTILINE)
            _path_pattern = re.compile(r'(?:/tmp/\S+|sandbox:/\S+)')

            # Add all previous step outputs, newest first (most recent context is most relevant)
            for idx, output in enumerate(reversed(previous_task_outputs)):
                if not output or len(output) < 20:
                    continue  # Skip trivial outputs
                # Remove blob URLs and local paths so agents use text data, not file downloads
                cleaned = _url_pattern.sub('', output)
                cleaned = _path_pattern.sub('[file]', cleaned).strip()
                if len(cleaned) < 20:
                    continue
                if total_chars + len(cleaned) > max_context_chars:
                    remaining = max_context_chars - total_chars
                    if remaining > 200:
                        context_parts.append(f"### Step Output {len(previous_task_outputs) - idx}:\n{cleaned[:remaining]}")
                    break
                context_parts.append(f"### Step Output {len(previous_task_outputs) - idx}:\n{cleaned}")
                total_chars += len(cleaned)

            combined_context = "\n\n".join(context_parts)
            log_info(f"[Agent Mode] SMART CONTEXT for '{recommended_agent}': selected {len(combined_context)} chars from {len(context_parts)} sources")

            enhanced_task_message = f"""{task_desc}

## Context from Previous Steps:
{combined_context}

IMPORTANT: All data you need is provided as text above. Create your output using this text data.
Do NOT attempt to download, open, or parse files from other agents — use the text content provided."""

        elif document_content:
            # No previous task outputs but we found document content in memory
            # This happens for the first parallel tasks in a workflow where no sequential
            # steps ran before them, but the user uploaded documents that were processed
            max_context_chars = 50000
            if len(document_content) > max_context_chars:
                document_content = document_content[:max_context_chars]

            log_info(f"[Agent Mode] SMART CONTEXT for '{recommended_agent}': no previous outputs, using DocumentProcessor memory ({len(document_content)} chars)")

            enhanced_task_message = f"""{task_desc}

## Document Content (from uploaded files):
{document_content}

IMPORTANT: Use the text content above to complete your task. All required data has been
extracted and is included in this message. Do NOT attempt to open or parse attached files
that are not in your native format — use the text content provided instead."""
        
        # File deduplication for multi-step workflows
        self._deduplicate_workflow_files(session_context)
        
        # EXPLICIT FILE ROUTING: Extract file URIs from _latest_processed_parts
        file_uris = []
        if hasattr(session_context, '_latest_processed_parts'):
            file_uris = self._extract_file_uris_from_parts(session_context._latest_processed_parts)
            log_debug(f"[Agent Mode] Passing {len(file_uris)} file URIs to {recommended_agent}")
        
        # Create tool context and call agent
        dummy_context = DummyToolContext(session_context, self._azure_blob_client)
        
        responses = await self.send_message(
            agent_name=recommended_agent,
            message=enhanced_task_message,  # ✅ Now includes previous task outputs!
            tool_context=dummy_context,
            suppress_streaming=True,  # Suppress agent's internal streaming to avoid duplicates in workflow mode
            file_uris=file_uris  # Pass explicit file URIs
        )
        
        if not responses or len(responses) == 0:
            task.state = "failed"
            task.error_message = "No response from agent"
            task.updated_at = datetime.now(timezone.utc)
            log_error(f"[Agent Mode] No response from agent")
            return {"error": "No response from agent", "output": None}
        
        response_obj = responses[0] if isinstance(responses, list) else responses
        
        # Check for HITL (input_required) - only if THIS agent requested input
        # BUGFIX: Only pause if pending_input_agent matches the current agent
        if session_context.pending_input_agent and session_context.pending_input_agent == recommended_agent:
            log_info(f"[Agent Mode] Agent '{recommended_agent}' returned input_required")
            task.state = "input_required"
            task.updated_at = datetime.now(timezone.utc)
            
            output_text = extract_text_fn(response_obj)
            
            # CRITICAL: Store output in task so it's available when resuming
            # Without this, the HITL task's output would be lost on resume
            task.output = {"result": output_text}
            
            # Emit agent output so user can see what the agent sent (e.g., Teams message)
            # Use a higher limit (2000 chars) to avoid cutting off important info like invoice details
            if output_text and recommended_agent:
                display_output = output_text[:2000] + "…" if len(output_text) > 2000 else output_text
                await self._emit_granular_agent_event(
                    recommended_agent, display_output, context_id,
                    event_type="agent_output", metadata={"output_length": len(output_text), "hitl": True}
                )
            
            log_info(f"[Agent Mode] Waiting for user response to '{recommended_agent}'")
            await self._emit_granular_agent_event(
                recommended_agent, f"Waiting for your response...", context_id,
                event_type="info", metadata={"hitl": True}
            )
            
            return {"output": output_text, "hitl_pause": True}
        
        # Clear any stale pending_input_agent that doesn't match this agent
        if session_context.pending_input_agent and session_context.pending_input_agent != recommended_agent:
            log_info(f"[Agent Mode] Clearing stale pending_input_agent '{session_context.pending_input_agent}' (current agent: {recommended_agent})")
            session_context.pending_input_agent = None
            session_context.pending_input_task_id = None
        
        # Parse response
        if isinstance(response_obj, Task):
            task.state = response_obj.status.state
            task.output = {
                "task_id": response_obj.id,
                "state": response_obj.status.state,
                "result": str(response_obj.result) if hasattr(response_obj, 'result') and response_obj.result else None,
                "artifacts": [a.model_dump() for a in response_obj.artifacts] if response_obj.artifacts else []
            }
            task.updated_at = datetime.now(timezone.utc)
            
            if task.state == "failed":
                task.error_message = response_obj.status.message or "Task failed"
                log_error(f"[Agent Mode] Task failed: {task.error_message}")
                return {"error": task.error_message, "output": None}
            
            output_text = str(response_obj.result) if response_obj.result else ""

            # Collect artifacts using helper
            if response_obj.artifacts:
                artifact_texts = self._collect_artifacts(response_obj.artifacts, session_context)
                if artifact_texts:
                    output_text = f"{output_text}\n\nArtifacts:\n" + "\n".join(artifact_texts)

                # Emit file artifact events for the frontend (image/video previews in inference steps).
                # In workflow mode, suppress_streaming=True skips the SSE streaming path where these
                # events normally fire, so we emit them here after collecting artifacts.
                await self._emit_file_events_from_artifacts(
                    response_obj.artifacts, recommended_agent, context_id
                )

            # Strip markdown image references from output text — images are displayed
            # separately as FilePart artifacts in the frontend, so including them in text
            # causes duplicate rendering.
            import re
            output_text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', output_text)
            output_text = re.sub(r'\n{3,}', '\n\n', output_text).strip()

            # Emit agent output to workflow panel so users can see what the agent returned
            # Use a higher limit (2000 chars) to avoid cutting off important info
            if output_text and recommended_agent:
                display_output = output_text[:2000] + "…" if len(output_text) > 2000 else output_text
                await self._emit_granular_agent_event(
                    recommended_agent, display_output, context_id,
                    event_type="agent_output", metadata={"output_length": len(output_text)}
                )

            return {"output": output_text, "hitl_pause": False}
        else:
            # Simple string response (from send_message — list of Part objects).
            # If we reach here, send_message() returned successfully (failures raise).
            task.state = "completed"
            output_text = extract_text_fn(response_obj)
            task.output = {"result": output_text}
            task.updated_at = datetime.now(timezone.utc)

            # NOTE: FileParts are already stored in _latest_processed_parts by convert_parts()
            # inside send_message(). No need to collect them again here — doing so creates
            # duplicates that cause dedup to drop files.

            # Emit file events from _latest_processed_parts for this agent's output
            # This covers agents that return FileParts directly (not wrapped in Task artifacts)
            await self._emit_file_events_from_parts(
                session_context, recommended_agent, context_id
            )

            # Emit agent output to workflow panel
            if output_text and recommended_agent:
                display_output = output_text[:2000] + "…" if len(output_text) > 2000 else output_text
                await self._emit_granular_agent_event(
                    recommended_agent, display_output, context_id,
                    event_type="agent_output", metadata={"output_length": len(output_text)}
                )

            return {"output": output_text, "hitl_pause": False}

    async def _intelligent_route_selection(
        self,
        user_message: str,
        available_workflows: List[Dict[str, Any]],
        context_id: str
    ) -> RouteSelection:
        """
        Use LLM to intelligently select the best execution approach for the user's request.
        
        This is the "router" that decides whether to:
        - Use a specific pre-defined workflow (structured multi-step process)
        - Use agents directly (free-form multi-agent orchestration)
        - Respond directly (simple queries that don't need orchestration)
        
        Args:
            user_message: The user's request/goal
            available_workflows: List of workflow metadata dicts with keys:
                - name: Workflow name
                - description: What the workflow does
                - goal: The workflow's objective
                - steps: List of workflow steps (optional, for context)
            context_id: Conversation identifier
            
        Returns:
            RouteSelection with approach, selected_workflow, confidence, and reasoning
        """
        log_debug(f"[Route Selection] Analyzing request with {len(available_workflows)} available workflows")
        
        # Build workflow descriptions for the prompt
        workflow_descriptions = []
        for i, wf in enumerate(available_workflows, 1):
            wf_name = wf.get('name', f'Workflow {i}')
            wf_desc = wf.get('description', 'No description provided')
            wf_goal = wf.get('goal', '')
            
            desc = f"""**{wf_name}**
- Description: {wf_desc}
- Goal: {wf_goal if wf_goal else 'Execute the workflow steps'}"""
            
            # Optionally include step count or step preview
            if wf.get('steps'):
                steps = wf['steps']
                if isinstance(steps, list):
                    desc += f"\n- Steps: {len(steps)} steps"
                elif isinstance(steps, str):
                    step_count = len([l for l in steps.split('\n') if l.strip() and l.strip()[0].isdigit()])
                    desc += f"\n- Steps: {step_count} steps"
            
            workflow_descriptions.append(desc)
        
        workflows_text = "\n\n".join(workflow_descriptions)
        
        # Build available agents summary
        agent_descriptions = []
        for card in self.cards.values():
            agent_info = f"**{card.name}**: {card.description[:150]}..."
            if hasattr(card, 'skills') and card.skills:
                skill_names = [s.name for s in card.skills[:3]]  # First 3 skills
                agent_info += f" (Skills: {', '.join(skill_names)})"
            agent_descriptions.append(agent_info)
        
        agents_text = "\n".join(agent_descriptions) if agent_descriptions else "No agents available"
        
        # Debug: Log agents and workflows counts for troubleshooting
        log_debug(f"[Route Selection] Agents in registry: {len(agent_descriptions)}, Workflows: {len(available_workflows)}")
        if len(agent_descriptions) == 0:
            log_error(f"[Route Selection] WARNING: No agents registered in self.cards! This may cause routing issues.")
        
        system_prompt = f"""You are an intelligent routing assistant. Analyze the user's request and decide the best execution approach.

### 📋 AVAILABLE WORKFLOWS
Pre-defined multi-step processes with specific sequences of agent calls.

{workflows_text}

### 🤖 AVAILABLE AGENTS
Specialized agents that can handle specific tasks independently.

{agents_text}

### 🎯 DECISION RULES (IN PRIORITY ORDER)

**1. Choose "workflow"** when:
- User's goal clearly matches ONE workflow's description or purpose
- User explicitly mentions a workflow name (even if they also mention an agent)
- The task requires the specific coordinated steps defined in a workflow
- Example: "Run the invoice workflow" → workflow
- Example: "Use QuickBooks to run the invoice workflow" → workflow (workflow name takes priority)

**2. Choose "workflows_parallel"** when:
- User's request matches TWO OR MORE workflows that should run SIMULTANEOUSLY
- The workflows are INDEPENDENT and don't depend on each other's output
- User explicitly asks for multiple things that map to different workflows
- Example: "Run the legal review AND the financial analysis" → workflows_parallel

**3. Choose "single_agent"** when:
- User explicitly names ONE specific agent and wants a simple, direct task
- The request is a single action that one agent can complete alone
- NO workflow matches the request
- Example: "Use the QuickBooks agent to list customers" → single_agent (QuickBooks)
- Example: "Ask the image generator to create a cat picture" → single_agent (Image Generator)
- Set selected_agent to the agent name

**4. Choose "multi_agent"** when:
- Task requires coordination between MULTIPLE agents but NO workflow fits
- User describes a complex goal that needs different agent capabilities combined
- User wants something custom/ad-hoc that spans multiple agent domains
- Example: "Research competitors and then create a marketing report" → multi_agent
- Example: "Get customer data and generate an invoice image" → multi_agent

**5. Choose "direct"** when:
- Simple question that requires NO agent capabilities
- General conversation, greetings, or meta-questions about the system
- Information that the host already knows (e.g., "what agents are available?")
- Example: "Hello" → direct
- Example: "What can you do?" → direct

### ⚠️ PRIORITY RULES
1. Workflow name mentioned → prefer "workflow" (even if agent also mentioned)
2. Single agent + simple task → use "single_agent" (skip orchestration overhead)
3. Complex multi-step task with no workflow → use "multi_agent"
4. When in doubt between single_agent and multi_agent → choose single_agent

### 📤 OUTPUT FORMAT
Return a JSON object with:
- approach: "workflow" | "workflows_parallel" | "single_agent" | "multi_agent" | "direct"
- selected_workflow: Name of workflow (if approach="workflow") or null
- selected_workflows: List of workflow names (if approach="workflows_parallel") or null  
- selected_agent: Name of agent (if approach="single_agent") or null
- confidence: 0.0 to 1.0 (how confident you are in this choice)
- reasoning: Brief explanation of your decision"""

        user_prompt = f"""User request: {user_message}

Analyze this request and decide the best approach."""

        try:
            selection = await self._call_azure_openai_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=RouteSelection,
                context_id=context_id
            )
            
            if selection.approach == "workflows_parallel":
                log_debug(f"[Route Selection] Decision: approach={selection.approach}, workflows={selection.selected_workflows}, confidence={selection.confidence}")
            else:
                log_debug(f"[Route Selection] Decision: approach={selection.approach}, workflow={selection.selected_workflow}, confidence={selection.confidence}")
            log_debug(f"[Route Selection] Reasoning: {selection.reasoning}")
            
            return selection
            
        except Exception as e:
            log_error(f"[Route Selection] Error during selection: {e}")
            # Fallback to multi_agent approach on error
            return RouteSelection(
                approach="multi_agent",
                selected_workflow=None,
                selected_workflows=None,
                selected_agent=None,
                confidence=0.5,
                reasoning=f"Fallback to multi_agent due to selection error: {str(e)}"
            )

    @staticmethod
    def _parse_workflow_steps(workflow: str) -> List[Dict[str, str]]:
        """Parse ALL steps from workflow text, handling multi-line descriptions.

        Returns a list of dicts with keys: label, agent, description.
        Multi-line descriptions (continuation lines that don't start a new step)
        are joined with spaces into a single description string.
        """
        # Step header patterns
        # Parallel: 1a. [Agent] description
        # Sequential: 1. [Agent] description
        step_pattern = re.compile(r'^(\d+[a-z]?)\.\s*\[(.+?)\]\s*(.+)')
        # Lines that start a new structural element (step, branch, blank)
        new_element_pattern = re.compile(r'^(\d+[a-z]?)\.\s*\[|^IF-|^\s*$', re.IGNORECASE)

        steps: List[Dict[str, str]] = []
        lines = workflow.strip().split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            match = step_pattern.match(line)
            if match:
                label = match.group(1)
                agent = match.group(2)
                description = match.group(3)
                # Consume continuation lines
                while i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if not next_line or new_element_pattern.match(next_line):
                        break
                    description += ' ' + next_line
                    i += 1
                steps.append({
                    "label": label,
                    "agent": agent,
                    "description": description,
                })
            i += 1
        return steps

    def _expand_parallel_from_workflow(
        self,
        workflow: str,
        next_task: Dict[str, Any],
        completed_tasks: List[Any],
    ) -> Optional[List[Dict[str, str]]]:
        """Detect if the LLM's single next_task belongs to a parallel group in the
        workflow text and expand it to all sibling tasks.

        Parallel groups are steps with the same number but different letter suffixes,
        e.g. ``1a. [Agent] desc`` and ``1b. [Agent] desc``.

        Returns a list of task dicts (for ``next_tasks``) if expansion applies,
        or ``None`` if no expansion is needed.
        """
        # Parse parallel groups from workflow text (handles multi-line descriptions)
        # Map: step_number -> [{"label": "1a", "agent": "...", "description": "..."}]
        parallel_groups: Dict[int, List[Dict[str, str]]] = {}
        for step in self._parse_workflow_steps(workflow):
            label = step["label"]
            # Only parallel steps (with letter suffix)
            m = re.match(r'^(\d+)([a-z])$', label)
            if not m:
                continue
            step_num = int(m.group(1))
            if step_num not in parallel_groups:
                parallel_groups[step_num] = []
            parallel_groups[step_num].append(step)

        if not parallel_groups:
            return None

        # Filter to only groups with 2+ entries (actual parallelism)
        parallel_groups = {k: v for k, v in parallel_groups.items() if len(v) >= 2}
        if not parallel_groups:
            return None

        # Determine which parallel groups have already been executed
        # by checking completed tasks for step labels
        executed_group_nums = set()
        for task in completed_tasks:
            desc = getattr(task, 'task_description', '') or ''
            step_match = re.search(r'\[Step\s+(\d+)[a-z]\]', desc)
            if step_match:
                executed_group_nums.add(int(step_match.group(1)))

        # Try to match the LLM's next_task to an unexecuted parallel group
        task_agent = (next_task.get("recommended_agent") or "").strip()
        task_desc = (next_task.get("task_description") or "").strip()

        for step_num in sorted(parallel_groups.keys()):
            if step_num in executed_group_nums:
                continue  # Already executed this group

            group = parallel_groups[step_num]
            # Check if the proposed task matches ANY entry in this parallel group
            for entry in group:
                entry_agent = entry["agent"]
                # Fuzzy agent name matching (one contains the other)
                agent_match = (
                    entry_agent.lower() in task_agent.lower()
                    or task_agent.lower() in entry_agent.lower()
                )
                if agent_match:
                    log_info(
                        f"🔀 [Parallel Expansion] Task agent '{task_agent}' matches "
                        f"group {step_num} ({len(group)} tasks: "
                        f"{', '.join(e['label'] for e in group)})"
                    )
                    return [
                        {
                            "task_description": e["description"],
                            "recommended_agent": e["agent"],
                        }
                        for e in group
                    ]

        return None

    async def _agent_mode_orchestration_loop(
        self,
        user_message: str,
        context_id: str,
        session_context: SessionContext,
        event_logger=None,
        workflow: Optional[str] = None,
        workflow_goal: Optional[str] = None
    ) -> List[str]:
        """
        Execute agent-mode orchestration: AI-driven task decomposition and multi-agent coordination.
        
        This is the core intelligence loop that:
        1. Uses Azure OpenAI to analyze the user's goal and available agents
        2. Breaks down complex requests into discrete, delegable tasks
        3. Selects the best agent for each task based on skills and capabilities
        4. Executes tasks sequentially or in parallel as appropriate
        5. Synthesizes results from multiple agents into coherent responses
        6. Adapts to failures, rate limits, and user feedback dynamically
        
        The loop continues until the goal is marked "completed" by the orchestrator LLM
        or the maximum iteration limit is reached (safety mechanism).
        
        Args:
            user_message: The user's original request or follow-up message
            context_id: Conversation identifier for state management
            session_context: Session state with agent task tracking
            event_logger: Optional callback for logging orchestration events
            workflow: Optional predefined workflow steps to enforce
            workflow_goal: Optional goal from workflow designer for completion evaluation
            
        Returns:
            List of response strings from executed tasks for final synthesis
        """
        log_debug(f"[Agent Mode] Starting orchestration loop for goal: {user_message[:100]}...")
        
        # Reset host token usage for this workflow
        self.host_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        # Emit typed init event for structured frontend (replaces old untyped _emit_status_event)
        await self._emit_granular_agent_event(
            "foundry-host-agent", "Initializing orchestration...", context_id,
            event_type="phase", metadata={"phase": "init"}
        )
        
        # =====================================================================
        # PLAN PERSISTENCE: Resume existing plan if user is providing follow-up info
        # =====================================================================
        # If an agent asked for more info in the previous turn, we saved the plan.
        # Now we resume it with the user's follow-up message instead of starting fresh.
        # This preserves the full task history and allows the orchestrator to continue.
        # =====================================================================
        existing_plan = session_context.current_plan
        if existing_plan:
            log_info(f"[Agent Mode] Resuming existing plan with {len(existing_plan.tasks)} tasks")
            log_info(f"[Agent Mode] PLAN DETAILS: {existing_plan.model_dump_json(indent=2)}")
            await self._emit_granular_agent_event(
                "foundry-host-agent", "Resuming workflow with your input...", context_id,
                event_type="phase", metadata={"phase": "resume"}
            )
            
            # Restore workflow and workflow_goal from the saved plan
            # This ensures the workflow instructions are re-injected into the planner prompt
            if existing_plan.workflow:
                workflow = existing_plan.workflow
                log_info(f"[Agent Mode] Restored workflow from plan ({len(workflow)} chars)")
            if existing_plan.workflow_goal:
                workflow_goal = existing_plan.workflow_goal
                log_info(f"[Agent Mode] Restored workflow_goal from plan")
            
            # Update the goal to include the user's follow-up
            original_goal = existing_plan.goal
            existing_plan.goal = f"{original_goal}\n\n[User Provided Additional Info]: {user_message}"
            existing_plan.goal_status = "incomplete"  # Reset to continue processing
            existing_plan.updated_at = datetime.now(timezone.utc)
            
            # Mark input_required tasks as completed with the user's response
            # This tells the orchestrator that the HITL step is done
            for task in existing_plan.tasks:
                if task.state == "input_required":
                    task.state = "completed"
                    task.output = task.output or {}
                    task.output["user_response"] = user_message
                    task.updated_at = datetime.now(timezone.utc)
                    log_info(f"[Agent Mode] Marked task '{task.task_id}' as completed with user response")
            
            # Use the existing plan instead of creating a new one
            plan = existing_plan
            
            # Clear the saved plan and HITL flag - we're resuming now
            session_context.current_plan = None
            session_context.pending_input_agent = None
            session_context.pending_input_task_id = None
            
            # Collect outputs from previously completed tasks for context
            all_task_outputs = []
            for task in plan.tasks:
                if task.state == "completed" and task.output:
                    # Task outputs use "result" key
                    # Fall back to "text" for compatibility, then str() as last resort
                    output_text = task.output.get("result", "") or task.output.get("text", "") or str(task.output)
                    if output_text:
                        all_task_outputs.append(output_text)
                        # Debug: Log output lengths to help diagnose context issues
                        log_info(f"   � Task '{task.task_id}': output={len(output_text)} chars")
            
            log_info(f"[Agent Mode] Resumed plan: {len(plan.tasks)} existing tasks, {len(all_task_outputs)} outputs")
            # Debug: Log which output is longest (likely has the data we need)
            if all_task_outputs:
                sizes = [(i, len(o)) for i, o in enumerate(all_task_outputs)]
                log_info(f"   Output sizes: {sizes}")
            
            # Variables needed for the orchestration loop
            iteration = 0
            max_iterations = 20
            workflow_step_count = 0
            extract_text_from_response = self._extract_text_from_response
            
            # Determine current step number from existing tasks (for HITL resume)
            # Find the highest step number from existing tasks to continue from there
            current_step_number = 0
            for task in plan.tasks:
                step_match = re.search(r'\[Step\s+(\d+)', task.task_description)
                if step_match:
                    step_num = int(step_match.group(1))
                    if step_num > current_step_number:
                        current_step_number = step_num
            log_info(f"[Agent Mode] Resuming from step {current_step_number}")
        else:
            # =====================================================================
            # LLM ORCHESTRATION PATH: All workflows go through the orchestrator
            # =====================================================================
            # The LLM orchestrator handles both sequential and parallel workflows.
            # For parallel steps (e.g., 2a., 2b.), the LLM will return next_tasks
            # with parallel=True, and we execute them via asyncio.gather().
            # =====================================================================
            # orchestrator LLM decides which agents to call and in what order.
            # =====================================================================
            
            # Handle conversation continuity - distinguish new goals from follow-up clarifications
            if context_id in self._active_conversations and not workflow:
                original_goal = self._active_conversations[context_id]
                goal_text = f"{original_goal}\n\n[Additional Information Provided]: {user_message}"
            else:
                # Use workflow_goal from the designer if provided, otherwise fall back to user_message
                if workflow_goal and workflow_goal.strip():
                    goal_text = workflow_goal
                    log_debug(f"[Workflow Mode] Using workflow designer goal: {goal_text[:100]}...")
                else:
                    goal_text = user_message
                if context_id not in self._active_conversations:
                    self._active_conversations[context_id] = goal_text
            
            # Use the class method for extracting clean text from A2A response objects
            extract_text_from_response = self._extract_text_from_response
            
            # Initialize execution plan with empty task list
            # Store workflow and workflow_goal for HITL resume scenarios
            plan = AgentModePlan(
                goal=goal_text, 
                goal_status="incomplete",
                workflow=workflow if workflow and workflow.strip() else None,
                workflow_goal=workflow_goal if workflow_goal and workflow_goal.strip() else None
            )
            iteration = 0
            max_iterations = 20
            workflow_step_count = 0
            
            # Initialize step tracking for workflow mode
            current_step_number = 0
            
            # Accumulate outputs from all completed tasks
            all_task_outputs = []
        
        # System prompt that guides the orchestrator's decision-making
        # This is the "brain" that decides which agents to use and when
        system_prompt = """You are the Host Orchestrator in an A2A multi-agent system.

PRIMARY RESPONSIBILITIES:
- **FIRST**: Check if a MANDATORY WORKFLOW exists below - if it does, you MUST complete ALL workflow steps before marking goal as "completed"
- Evaluate whether the user's goal is achieved by analyzing all completed tasks and their outputs
- If incomplete, propose the next task(s) that move closer to the goal
- Select the most appropriate agent based on their specialized skills

DECISION-MAKING RULES:
- Analyze the ENTIRE plan history - don't ignore previous tasks or outputs
- Never repeat completed tasks unless explicitly retrying a failure
- Keep each task atomic and delegable to a single agent
- Match tasks to agents using their "skills" field for best results
- If no agent fits, set recommended_agent=null
- Mark goal_status="completed" ONLY when: (1) ALL MANDATORY WORKFLOW steps are completed (if workflow exists), AND (2) the objective is fully achieved

### 🛑 AGENT ASKS FOR MORE INFO - STOP AND COMPLETE
If an agent's response asks for more information (e.g., "I need customer details", "Please provide..."):
- Do NOT call the same agent again trying to provide the info
- Do NOT fabricate or make up the missing information
- Mark goal_status="completed" and include the agent's question in your reasoning
- The user will see the agent's question and can provide the needed info in their next message
- This prevents infinite loops of calling the same agent repeatedly

### 🚫 DO NOT RETRY FAILED STEPS
If an agent responds but could not complete its task due to API rate limits, service unavailability, or other external issues:
- The step is DONE — do NOT call the same agent again for the same step
- Move on to the next workflow step immediately
- Rate limits do not resolve with immediate retries — retrying wastes time
- Include the limitation in your final reasoning so the user knows what happened
- The user can re-run the workflow later when limits reset

### 🔀 PARALLEL EXECUTION SUPPORT
When the workflow contains parallel steps (indicated by letter suffixes like 2a., 2b., 2c.):
- These steps can be executed SIMULTANEOUSLY - they do not depend on each other
- Use `next_tasks` (list) instead of `next_task` (single) to propose multiple parallel tasks
- Set `parallel=true` to indicate these tasks should run concurrently
- Example: For steps "2a. Legal review" and "2b. Technical assessment":
  ```json
  {
    "goal_status": "incomplete",
    "next_task": null,
    "next_tasks": [
      {"task_description": "Legal review of requirements", "recommended_agent": "Legal Agent"},
      {"task_description": "Technical assessment", "recommended_agent": "Tech Agent"}
    ],
    "parallel": true,
    "reasoning": "Steps 2a and 2b can run in parallel as they are independent"
  }
  ```
- After parallel tasks complete, proceed to the next sequential step (e.g., step 3)
- If NO parallel steps, use `next_task` (single) and set `parallel=false`

### 🚨 CRITICAL: WHEN TO USE PARALLEL EXECUTION
**ALWAYS use parallel execution (next_tasks + parallel=true) when:**
1. User requests MULTIPLE similar items (e.g., "generate 3 images", "create 2 documents")
2. Workflow steps have letter suffixes (1a, 1b, 1c or 2a, 2b)
3. Tasks are independent and can run simultaneously
4. User explicitly says "in parallel", "simultaneously", or "at the same time"

**Example - User says "Generate 3 images: a car, a bike, a backpack":**
```json
{
  "goal_status": "incomplete",
  "next_task": null,
  "next_tasks": [
    {"task_description": "Generate an image of a car", "recommended_agent": "AI Foundry Image Generator Agent"},
    {"task_description": "Generate an image of a bike", "recommended_agent": "AI Foundry Image Generator Agent"},
    {"task_description": "Generate an image of a backpack", "recommended_agent": "AI Foundry Image Generator Agent"}
  ],
  "parallel": true,
  "reasoning": "User requested 3 independent images - executing in parallel for efficiency"
}
```

**DO NOT bundle multiple items into a single task like "Generate 3 images" - split them into separate parallel tasks!**

MULTI-AGENT STRATEGY:
- **MAXIMIZE AGENT UTILIZATION**: Break complex goals into specialized subtasks
- Use multiple agents when their combined expertise adds value
- Don't force one agent to handle everything when others can help
- The same agent can be used multiple times for related subtasks

FAILURE HANDLING:
- Consider failed tasks in planning
- You can retry with modifications or try alternative agents/approaches

### 🔄 TASK DECOMPOSITION PRINCIPLES
- **Read ALL Agent Skills First**: Before creating any task, carefully read through the skill descriptions of ALL available agents to understand what each can provide.
- **Identify Skill Dependencies**: Determine if completing the goal requires outputs from multiple agents. If Agent B needs information/context that Agent A specializes in, Agent A must be tasked first.
- **Match Task to Skill Domain**: Each task should align with exactly ONE agent's skill domain. If a concept in the goal matches words in an agent's skill name or description, that agent should handle that aspect.
- **Information Producers vs Consumers**: Some agents produce information/context/specifications (e.g., skills about "guidelines", "direction", "specifications"). Others consume that information to execute (e.g., skills about "generate", "create", "build"). Producers come first.
- **Sequential Task Chain**: When the goal involves multiple skill domains, create Task 1 for the information producer, let it complete, then Task 2 for the executor using Task 1's output.
- **No Shortcuts**: Don't try to have one agent do another agent's specialty work. Decompose properly even if it means more tasks.

### 🎯 DELEGATION FIRST PRINCIPLE
- ALWAYS delegate to an appropriate agent if you have ANY actionable information related to the goal
- **BUT** check if the task requires prerequisite skills from a different agent - if so, delegate to that agent FIRST
- Each agent should work within their skill domain - use the "skills" field to match task requirements to agent capabilities
- Tasks should arrive at agents with all necessary context already gathered by appropriate upstream agents
"""
        
        # Inject workflow if provided
        log_debug(f"[Agent Mode] Checking workflow: workflow={workflow}, stripped={workflow.strip() if workflow else 'N/A'}")
        if workflow and workflow.strip():
            workflow_section = f"""

### 🔥 MANDATORY WORKFLOW - FOLLOW ALL STEPS IN ORDER 🔥
**CRITICAL**: The following workflow steps are MANDATORY and must ALL be completed before marking the goal as "completed".
Do NOT skip steps. Do NOT mark goal as completed until ALL workflow steps are done.

{workflow.strip()}

**AGENT ROUTING**:
- Each step specifies the agent to use in [brackets] - e.g., "[QuickBooks Online Agent]"
- You MUST use the agent specified in brackets for that step - do NOT substitute a different agent
- Set `recommended_agent` to the exact agent name from the brackets
- Steps marked [EVALUATE] are handled by the host orchestrator — set recommended_agent to "EVALUATE"
- Steps marked [QUERY] are handled by the host orchestrator — set recommended_agent to "QUERY"
- Steps marked [WEB_SEARCH] are handled by the host orchestrator — set recommended_agent to "WEB_SEARCH"

**WEB SEARCH STEPS**:
- [WEB_SEARCH] steps search the web using Bing for current, real-time information
- Use them for live data: exchange rates, weather, news, current prices, etc.
- Their text output is available to subsequent steps (e.g., a [QUERY] step can analyze web search results)

**QUERY STEPS**:
- [QUERY] steps analyze previous outputs and return structured JSON results (they do NOT branch)
- Use them to filter, compare, rank, or extract information from previous step outputs
- Their JSON output is available to subsequent steps in the workflow

**EVALUATION & BRANCHING**:
- Steps with [EVALUATE] are conditional decision points that return true or false
- After an [EVALUATE] step completes, its result (true/false) will appear in the task output
- `IF-TRUE →` lines indicate the step to follow when the evaluation is true
- `IF-FALSE →` lines indicate the step to follow when the evaluation is false
- **CRITICAL**: Only follow the branch that matches the evaluation result. NEVER execute the other branch.
- Steps in the skipped branch must NOT be proposed or executed
- After the branch step completes, continue to the next sequential step (the merge point)

**TASK DESCRIPTIONS** (CRITICAL):
- The `task_description` field MUST contain the COMPLETE text from the workflow step — copy it VERBATIM
- Do NOT summarize, shorten, or paraphrase workflow step instructions
- Include ALL details: entity names, parameters, time ranges, specific values, analysis requirements
- Example: if the step says "Get RSI (14-day) for GHRS over the last 100 days. Summarize signals.", the task_description must include ALL of that text

**EXECUTION RULES**:
- Execute sequential steps (1, 2, 3) one after another
- **PARALLEL STEPS** (e.g., 2a, 2b, 2c): When you see steps with letter suffixes, these can run SIMULTANEOUSLY
  - Use `next_tasks` (list) with `parallel=true` to execute them concurrently
  - Wait for ALL parallel tasks to complete before moving to the next sequential step
- Only mark goal_status="completed" after ALL required workflow steps are finished
- Skipped branch steps do NOT count toward the completion requirement
- **DEPENDENCY-AWARE FAILURE HANDLING**: If a step fails and a subsequent step DEPENDS on its output (e.g., Step 2 needs data produced by Step 1), mark the dependent step as failed immediately with error_message explaining the missing upstream data — do NOT dispatch it to an agent. Agents cannot fulfill tasks when required input data is unavailable.
- If a step fails but subsequent steps are INDEPENDENT (do not need its output), continue executing them normally
- You may retry a failed step itself, but never send a dependent step to an agent with missing data — that wastes time and produces misleading "completed" results
"""
            system_prompt += workflow_section
            log_debug(f"[Agent Mode] Injected workflow into planner prompt ({len(workflow)} chars)")
        
        # Add workflow-specific completion logic if workflow is present
        if workflow and workflow.strip():
            # Count steps, accounting for branching (IF-TRUE/IF-FALSE)
            # Top-level steps: lines starting with a digit (no leading whitespace)
            # Branch lines: indented IF-TRUE/IF-FALSE lines — only ONE branch executes per eval
            top_level_steps = 0
            branch_pairs = 0
            has_branching = False
            for line in workflow.strip().split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped[0].isdigit() or stripped.startswith('-'):
                    if not line[0].isspace() or line.startswith('-'):
                        # Top-level step (not indented)
                        top_level_steps += 1
                if stripped.upper().startswith('IF-TRUE'):
                    branch_pairs += 1
                    has_branching = True

            if has_branching:
                # Each branch pair adds 1 execution (one of true/false runs)
                workflow_step_count = top_level_steps + branch_pairs
            else:
                workflow_step_count = top_level_steps
            log_debug(f"[Agent Mode] Workflow step count: {workflow_step_count} (top_level={top_level_steps}, branches={branch_pairs})")

            branching_note = ""
            if has_branching:
                branching_note = f"""
- **BRANCHING**: This workflow has evaluation branches (IF-TRUE/IF-FALSE). Only ONE branch executes per evaluation.
- Skipped branch steps do NOT count toward the completion requirement.
- Expected completed tasks: {workflow_step_count} (= {top_level_steps} main steps + {branch_pairs} branch step(s), one per evaluation)"""

            system_prompt += f"""

### 🚨 CRITICAL: WHEN TO STOP (WORKFLOW MODE)
- A WORKFLOW IS ACTIVE with approximately **{workflow_step_count} REQUIRED STEPS** to complete
- **STEP COUNTING**: Count your completed tasks carefully!{branching_note}
- **VERIFICATION CHECKLIST**:
  1. Count the number of workflow steps above
  2. Count the number of successfully completed tasks in your plan
  3. Match each workflow step to a completed task
  4. If required steps are not yet completed, goal_status MUST be "incomplete"
- **COMPLETION CRITERIA** - Mark goal_status="completed" ONLY when:
  1. All required workflow steps have been attempted (each step dispatched to its agent once), AND
  2. There are no remaining unattempted workflow steps
- A step counts as "attempted" even if the agent hit rate limits or returned an error — do NOT retry it
- **WARNING**: Do NOT mark as completed prematurely!
- If ANY required workflow step has not been attempted yet, goal_status MUST be "incomplete" and you must create the next task"""
        else:
            system_prompt += """

### 🚨 CRITICAL: WHEN TO STOP (LOOP DETECTION & USER INPUT)
- ONLY mark goal as "completed" in these specific cases:
  1. The goal is actually fully accomplished with successful task outputs
  2. You have 2+ completed tasks where agents explicitly asked the USER for information
  3. The last agent response clearly states they need user input to proceed
- If NO tasks have been created yet, DO NOT mark as completed - create a task first!
- When agents request information, synthesize their questions and present to the user
- When the user provides information in a follow-up, create a NEW task with that information"""
        
        while plan.goal_status == "incomplete" and iteration < max_iterations:
            iteration += 1
            log_debug(f"[Agent Mode] Iteration {iteration}/{max_iterations}")
            
            # =========================================================
            # CANCELLATION CHECK: Between steps, bail if user cancelled
            # =========================================================
            if self.is_cancelled(context_id):
                log_info(f"[CANCEL] Workflow cancelled at iteration {iteration}, stopping orchestration loop")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", "Workflow cancelled by user", context_id,
                    event_type="phase", metadata={"phase": "cancelled"}
                )
                return all_task_outputs + ["[Workflow cancelled by user]"]

            # =========================================================
            # INTERRUPT CHECK: Between steps, check if user redirected
            # =========================================================
            interrupt_instruction = self.get_interrupt(context_id)
            if interrupt_instruction:
                log_info(f"[INTERRUPT] Detected interrupt between steps: {interrupt_instruction[:80]}...")
                completed_tasks = [t for t in plan.tasks if t.state == "completed"]
                original_goal = plan.goal
                plan.goal = self._build_interrupted_goal(original_goal, interrupt_instruction, completed_tasks)
                plan.goal_status = "incomplete"
                plan.updated_at = datetime.now(timezone.utc)
                await self._emit_granular_agent_event(
                    "foundry-host-agent",
                    f"⚡ Workflow redirected: {interrupt_instruction[:100]}",
                    context_id,
                    event_type="phase",
                    metadata={"phase": "interrupted", "new_instruction": interrupt_instruction}
                )
                await self._emit_plan_update(plan, context_id, reasoning=f"Redirected: {interrupt_instruction[:100]}")
                log_info(f"[INTERRUPT] Goal updated, re-planning with {len(completed_tasks)} completed tasks preserved")

            # Emit a user-visible "planning" event on the first iteration so the
            # frontend shows activity instead of a blank "Starting workflow..." screen
            if iteration == 1:
                await self._emit_granular_agent_event(
                    "foundry-host-agent", "Planning workflow steps...", context_id,
                    event_type="phase", metadata={"phase": "workflow_planning"}
                )

            # Single typed event replaces old untyped _emit_status_event + typed double-emit
            await self._emit_granular_agent_event(
                "foundry-host-agent", f"Planning step {iteration}...", context_id,
                event_type="phase", metadata={"phase": "planning", "step_number": iteration}
            )
            
            # Emit plan at start of each iteration so frontend shows current state
            await self._emit_plan_update(plan, context_id, reasoning=f"Planning step {iteration}...")
            
            # Build user prompt with current plan state
            available_agents = []
            for card in self.cards.values():
                agent_info = {
                    "name": card.name,
                    "description": card.description
                }
                
                # Add skills if present
                if hasattr(card, 'skills') and card.skills:
                    skills_list = []
                    for skill in card.skills:
                        skill_dict = {
                            "id": getattr(skill, 'id', ''),
                            "name": getattr(skill, 'name', ''),
                            "description": getattr(skill, 'description', ''),
                        }
                        skills_list.append(skill_dict)
                    agent_info['skills'] = skills_list
                
                available_agents.append(agent_info)

            # Add built-in pseudo-agents only when the workflow uses them,
            # so they don't confuse the planner for normal agent-routed steps
            workflow_upper = workflow.upper() if workflow else ""
            if '[EVALUATE]' in workflow_upper:
                available_agents.append({
                    "name": "EVALUATE",
                    "description": "Built-in host orchestrator capability. Evaluates a condition and returns TRUE/FALSE for workflow branching. Set recommended_agent to 'EVALUATE'."
                })
            if '[QUERY]' in workflow_upper:
                available_agents.append({
                    "name": "QUERY",
                    "description": "Built-in host orchestrator capability. Analyzes previous workflow outputs and returns structured JSON results. Can also answer general knowledge questions. Set recommended_agent to 'QUERY'."
                })
            if '[WEB_SEARCH]' in workflow_upper:
                available_agents.append({
                    "name": "WEB_SEARCH",
                    "description": "Built-in host orchestrator capability. Searches the web using Bing for current, real-time information (exchange rates, weather, news, prices). Set recommended_agent to 'WEB_SEARCH'."
                })

            # Debug: Log available agents count for troubleshooting
            agent_names = [a.get('name', 'Unknown') for a in available_agents]
            log_debug(f"[Planner] {len(available_agents)} agents available: {agent_names[:5]}{'...' if len(agent_names) > 5 else ''}")
            if iteration == 1:
                # Only show on first iteration to avoid spam
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"📋 {len(available_agents)} agents available for planning", context_id,
                    event_type="info", metadata={"agents_count": len(available_agents), "agent_names": agent_names[:5]}
                )
            
            # Build a compact version of the plan for the LLM prompt.
            # Full task outputs can be huge (agent responses) — truncate them
            # so the LLM can still reason about what happened without blowing
            # up the context window or degrading decision quality.
            compact_plan = plan.model_dump()
            for task_entry in compact_plan.get("tasks", []):
                output = task_entry.get("output")
                if output and isinstance(output, dict):
                    # Keep result field but truncate if too long
                    result_val = output.get("result")
                    if isinstance(result_val, str) and len(result_val) > 500:
                        output["result"] = result_val[:500] + "... [truncated]"
                    # Drop bulky nested fields the planner doesn't need
                    for drop_key in ("artifacts", "task_id"):
                        output.pop(drop_key, None)

            # In workflow mode, add an explicit step-completion map so the
            # LLM doesn't have to parse [Step X] prefixes from descriptions.
            workflow_progress = ""
            if workflow and workflow.strip():
                completed_steps = []
                pending_steps = []
                for task_entry in compact_plan.get("tasks", []):
                    step_match = re.search(r'\[Step\s+(\d+[a-z]?)\]', task_entry.get("task_description", ""))
                    if step_match:
                        label = step_match.group(1)
                        state = task_entry.get("state", "pending")
                        if state == "completed":
                            completed_steps.append(label)
                        else:
                            pending_steps.append(f"{label} ({state})")
                if completed_steps or pending_steps:
                    workflow_progress = f"\n\nWorkflow Progress:\n- Completed steps: {', '.join(completed_steps) if completed_steps else 'none'}\n- Pending/in-progress: {', '.join(pending_steps) if pending_steps else 'none'}"

            user_prompt = f"""Goal:
{plan.goal}

Current Plan (JSON):
{json.dumps(compact_plan, indent=2, default=str)}

Available Agents (JSON):
{json.dumps(available_agents, indent=2)}{workflow_progress}

Analyze the plan and determine the next step."""
            
            # Get next step from orchestrator
            try:
                next_step = await self._call_azure_openai_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=NextStep,
                    context_id=context_id
                )
                
                log_debug(f"[Agent Mode] Orchestrator: {next_step.reasoning[:100]}... | status={next_step.goal_status}")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", next_step.reasoning, context_id,
                    event_type="reasoning", metadata={"step_number": iteration, "goal_status": next_step.goal_status}
                )
                
                # Update plan status
                plan.goal_status = next_step.goal_status
                plan.updated_at = datetime.now(timezone.utc)
                
                if next_step.goal_status == "completed":
                    completed_tasks_count = len([t for t in plan.tasks if t.state == "completed"])
                    input_required_tasks = [t for t in plan.tasks if t.state == "input_required"]
                    log_info(f"[Agent Mode] Goal completed after {iteration} iterations ({completed_tasks_count} completed, {len(input_required_tasks)} input_required)")
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", "Goal achieved! Generating final response...", context_id,
                        event_type="phase", metadata={"phase": "complete", "tasks_completed": completed_tasks_count, "iterations": iteration}
                    )
                    
                    # Emit final plan state
                    await self._emit_plan_update(plan, context_id, reasoning="Goal completed")
                    
                    # =========================================================
                    # PLAN PERSISTENCE: Save plan if agent needs user input
                    # =========================================================
                    # If any task has state="input_required", save the plan so
                    # the next turn can resume. This handles the HITL case where 
                    # an agent asks for more info - we save the plan so we can 
                    # resume when user provides the requested information.
                    # =========================================================
                    if input_required_tasks:
                        log_info(f"[Agent Mode] Saving plan for resume - agent(s) need user input")
                        for t in input_required_tasks:
                            log_info(f"   Task '{t.task_id}': {t.task_description[:50]}...")
                        session_context.current_plan = plan
                    
                    break
                
                # =========================================================
                # TASK EXECUTION: Handle both sequential and parallel tasks
                # =========================================================

                # =========================================================
                # PARALLEL EXPANSION: Ensure ALL siblings from a parallel
                # group in the workflow text execute together in one batch.
                #
                # Two cases:
                # A) LLM sends single next_task → expand to all siblings
                # B) LLM sends next_tasks with partial group (e.g., 3 of 5)
                #    → expand to include the missing siblings
                # =========================================================
                if workflow and workflow.strip():
                    _has_next_task = bool(next_step.next_task)
                    _has_next_tasks = bool(next_step.next_tasks) and len(next_step.next_tasks) > 1
                    log_info(
                        f"[Parallel Expansion] next_task={_has_next_task}, "
                        f"next_tasks={len(next_step.next_tasks) if next_step.next_tasks else 0}, "
                        f"→ Case {'A' if _has_next_task and not _has_next_tasks else 'B' if _has_next_tasks else 'NONE'}"
                    )
                    if (next_step.next_task
                            and not (next_step.next_tasks and len(next_step.next_tasks) > 1)):
                        # Case A: single task → expand to full parallel group
                        expanded = self._expand_parallel_from_workflow(
                            workflow, next_step.next_task, plan.tasks
                        )
                        if expanded:
                            log_info(f"[Parallel Expansion] Expanded single next_task into {len(expanded)} parallel tasks")
                            next_step.next_tasks = expanded
                            next_step.next_task = None
                    elif next_step.next_tasks and len(next_step.next_tasks) > 1:
                        # Case B: LLM sent multiple tasks — check if they're a
                        # parallel group and replace with full workflow-text descriptions.
                        # The LLM often truncates/summarizes descriptions; the workflow
                        # text is the authoritative source.
                        for proposed_task in next_step.next_tasks:
                            expanded = self._expand_parallel_from_workflow(
                                workflow, proposed_task, plan.tasks
                            )
                            if expanded and len(expanded) >= len(next_step.next_tasks):
                                if len(expanded) > len(next_step.next_tasks):
                                    log_info(
                                        f"[Parallel Expansion] LLM proposed {len(next_step.next_tasks)} "
                                        f"tasks but parallel group has {len(expanded)} — expanding to full group"
                                    )
                                else:
                                    log_info(
                                        f"[Parallel Expansion] Replacing LLM descriptions with full "
                                        f"workflow-text descriptions for {len(expanded)} parallel tasks"
                                    )
                                next_step.next_tasks = expanded
                                break

                # Determine which tasks to execute
                tasks_to_execute = []
                # Auto-detect parallel: if next_tasks has multiple entries, run them in parallel
                # regardless of the parallel flag (LLM doesn't reliably set it)
                is_parallel = next_step.next_tasks and len(next_step.next_tasks) > 1

                if is_parallel and next_step.next_tasks:
                    log_info(f"[Agent Mode] PARALLEL execution: {len(next_step.next_tasks)} tasks")
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", f"Executing {len(next_step.next_tasks)} tasks in parallel...", context_id,
                        event_type="phase", metadata={"phase": "parallel_execution", "task_count": len(next_step.next_tasks)}
                    )
                    for task_dict in next_step.next_tasks:
                        tasks_to_execute.append({
                            "task_description": task_dict.get("task_description"),
                            "recommended_agent": task_dict.get("recommended_agent")
                        })
                elif next_step.next_task:
                    # SEQUENTIAL EXECUTION: Single task via next_task
                    tasks_to_execute.append({
                        "task_description": next_step.next_task.get("task_description"),
                        "recommended_agent": next_step.next_task.get("recommended_agent")
                    })
                
                if not tasks_to_execute:
                    log_warning("[Agent Mode] No tasks to execute, breaking loop")
                    break

                # =========================================================
                # WORKFLOW DESCRIPTION ENFORCEMENT: Ensure agents receive
                # the FULL workflow step text, not LLM-truncated summaries.
                # Parse the workflow text and replace any task description
                # that is shorter than the authoritative workflow step.
                # =========================================================
                if workflow and workflow.strip():
                    # Parse all workflow steps using shared parser (handles multi-line descriptions)
                    _wf_steps = {}
                    for _ws in self._parse_workflow_steps(workflow):
                        _wf_steps[_ws["label"]] = {
                            "agent": _ws["agent"],
                            "description": _ws["description"],
                            "matched": False,
                        }

                    for task_dict in tasks_to_execute:
                        task_agent = (task_dict.get("recommended_agent") or "").strip().lower()
                        task_desc = (task_dict.get("task_description") or "").strip()
                        if not task_agent or not task_desc:
                            continue

                        # Strip "Use the X Agent" prefix that the LLM sometimes adds
                        clean_desc = re.sub(
                            r'^use\s+the\s+.+?\s+agent\s*', '', task_desc, flags=re.IGNORECASE
                        ).strip() or task_desc

                        # Find the best matching workflow step
                        best_label = None
                        best_desc = None
                        for label, ws in _wf_steps.items():
                            if ws["matched"]:
                                continue
                            ws_agent = ws["agent"].lower()
                            # Agent name match (fuzzy)
                            if ws_agent not in task_agent and task_agent not in ws_agent:
                                continue
                            # Check if the task desc is a prefix/substring of the workflow desc
                            if clean_desc.lower() in ws["description"].lower():
                                if best_desc is None or len(ws["description"]) > len(best_desc):
                                    best_label = label
                                    best_desc = ws["description"]

                        if best_desc and len(best_desc) > len(task_desc):
                            log_info(
                                f"[Workflow Enforcement] Replacing truncated description "
                                f"'{task_desc[:60]}' → '{best_desc[:80]}'"
                            )
                            task_dict["task_description"] = best_desc
                            _wf_steps[best_label]["matched"] = True

                # Log final task descriptions for debugging
                for _ti, _td in enumerate(tasks_to_execute):
                    log_info(f"[Task Descriptions] #{_ti}: agent={_td.get('recommended_agent')}, desc='{_td.get('task_description', '')[:100]}'")

                # Validate all tasks have descriptions
                for task_dict in tasks_to_execute:
                    if not task_dict.get("task_description"):
                        log_warning("[Agent Mode] Task missing description, skipping")
                        tasks_to_execute.remove(task_dict)
                
                if not tasks_to_execute:
                    log_warning("[Agent Mode] No valid tasks after validation, breaking loop")
                    break
                
                # =========================================================
                # LOOP DETECTION: Prevent infinite loops on failing agents
                # =========================================================
                # Track how many times we've called the same agent with similar tasks
                # If an agent keeps failing/completing without progress, stop
                # =========================================================
                max_same_agent_attempts = 3
                for task_dict in tasks_to_execute[:]:  # Use slice copy to allow removal
                    agent_name = task_dict.get("recommended_agent", "")
                    task_desc = task_dict.get("task_description", "").lower()
                    
                    # Count previous attempts to this agent
                    same_agent_tasks = [
                        t for t in plan.tasks 
                        if t.recommended_agent == agent_name
                    ]
                    
                    # Check for repeated similar tasks (e.g., "re-authenticate", same keywords)
                    similar_keywords = ["re-authenticate", "reconnect", "retry", "token", "auth"]
                    is_retry_task = any(kw in task_desc for kw in similar_keywords)
                    
                    if len(same_agent_tasks) >= max_same_agent_attempts:
                        # Check if we're making progress (different task types)
                        recent_tasks = same_agent_tasks[-max_same_agent_attempts:]
                        recent_descs = [t.task_description.lower() for t in recent_tasks]

                        # If recent tasks all have retry keywords, we're looping
                        retry_count = sum(1 for d in recent_descs if any(kw in d for kw in similar_keywords))

                        if retry_count >= 2 or is_retry_task:
                            log_error(f"[LOOP DETECTION] Agent '{agent_name}' has been called {len(same_agent_tasks)} times with repeated retry tasks. Breaking loop.")
                            # Emit as orchestrator event so it shows in the orchestrator section,
                            # NOT as a separate step card (which would confuse the user)
                            await self._emit_granular_agent_event(
                                "foundry-host-agent",
                                f"⚠️ Stopping retries for {agent_name} — the agent could not complete after {len(same_agent_tasks)} attempts (likely rate-limited or unavailable).",
                                context_id,
                                event_type="phase", metadata={"phase": "loop_detection", "agent": agent_name}
                            )
                            
                            # Remove this task from execution
                            tasks_to_execute.remove(task_dict)
                            
                            # Mark goal as completed to break the loop
                            plan.goal_status = "completed"
                            plan.updated_at = datetime.now(timezone.utc)
                
                if not tasks_to_execute or plan.goal_status == "completed":
                    if plan.goal_status == "completed":
                        log_info(f"[LOOP DETECTION] Goal marked completed due to loop detection")
                    break
                
                # Create AgentModeTask objects for all tasks
                # In workflow mode, prepend step labels for proper UI rendering
                pydantic_tasks = []

                # For parallel tasks, increment step number ONCE, then use letter suffixes
                if is_parallel and workflow and workflow.strip():
                    current_step_number += 1

                for task_idx, task_dict in enumerate(tasks_to_execute):
                    original_description = task_dict["task_description"]
                    recommended_agent = task_dict.get("recommended_agent", "")

                    # Determine the step label for this task
                    if workflow and workflow.strip():
                        if is_parallel:
                            # Parallel tasks get letter suffixes (e.g., 2a, 2b, 2c)
                            # current_step_number was already incremented above
                            step_label = f"{current_step_number}{chr(ord('a') + task_idx)}"
                        else:
                            # Sequential task - increment step number
                            current_step_number += 1
                            step_label = str(current_step_number)
                    else:
                        step_label = None  # No workflow, no step labeling
                    
                    # Build task description with step label
                    if step_label and not re.search(r'\[Step\s+\d+', original_description):
                        task_description = f"[Step {step_label}] {original_description}"
                    else:
                        task_description = original_description
                    
                    task = AgentModeTask(
                        task_id=str(uuid.uuid4()),
                        task_description=task_description,
                        recommended_agent=recommended_agent or None,
                        state="pending"
                    )
                    plan.tasks.append(task)
                    pydantic_tasks.append(task)
                    log_debug(f"[Agent Mode] Created task: {task.task_description[:50]}...")
                
                # Execute tasks (parallel or sequential)
                if is_parallel:
                    # ============================================
                    # PARALLEL EXECUTION via asyncio.gather()
                    # ============================================
                    import asyncio as async_lib  # Import locally to avoid any scoping issues

                    # Snapshot file parts BEFORE parallel execution starts.
                    # This prevents parallel sibling agents from seeing each other's
                    # output files (e.g., Word agent's .docx leaking to Excel agent).
                    _pre_parallel_parts = list(getattr(session_context, '_latest_processed_parts', []))

                    log_info(f"[Agent Mode] Executing {len(pydantic_tasks)} tasks IN PARALLEL")
                    await self._emit_granular_agent_event(
                        "foundry-host-agent", f"Executing {len(pydantic_tasks)} tasks simultaneously...", context_id,
                        event_type="phase", metadata={"phase": "parallel_execution", "task_count": len(pydantic_tasks)}
                    )
                    
                    async def execute_task_parallel(task: AgentModeTask) -> Dict[str, Any]:
                        """Execute a single task and return result dict."""
                        # Set parallel_call_id so WebSocket events include it for frontend grouping
                        _current_parallel_call_id.set(task.task_id)
                        task.state = "running"
                        task.updated_at = datetime.now(timezone.utc)

                        try:
                            # Restore pre-parallel file snapshot so this agent only sees
                            # files from PRIOR steps, not from sibling parallel agents
                            session_context._latest_processed_parts = list(_pre_parallel_parts)

                            # Pass ALL accumulated outputs as text context
                            previous_output = list(all_task_outputs) if all_task_outputs else None

                            result = await self._execute_orchestrated_task(
                                task=task,
                                session_context=session_context,
                                context_id=context_id,
                                workflow=workflow,
                                user_message=user_message,
                                extract_text_fn=extract_text_from_response,
                                previous_task_outputs=previous_output  # ✅ Only LAST output
                            )
                            return result
                        except Exception as e:
                            # IMPORTANT: Check if HITL was triggered before the error
                            recommended_agent = task.recommended_agent
                            if session_context.pending_input_agent and session_context.pending_input_agent == recommended_agent:
                                log_info(f"[Agent Mode] Parallel task exception but HITL triggered")
                                task.state = "input_required"
                                task.updated_at = datetime.now(timezone.utc)
                                return {"output": str(e), "hitl_pause": True, "task_id": task.task_id}
                            
                            task.state = "failed"
                            task.error_message = str(e)
                            task.updated_at = datetime.now(timezone.utc)
                            log_error(f"[Agent Mode] Parallel task failed: {e}")
                            return {"error": str(e), "task_id": task.task_id}
                    
                    # Run all tasks in parallel
                    try:
                        results = await async_lib.gather(
                            *[execute_task_parallel(t) for t in pydantic_tasks],
                            return_exceptions=True
                        )
                    except Exception as gather_error:
                        log_error(f"[Agent Mode] asyncio.gather failed: {gather_error}")
                        raise
                    
                    # Process results — emit completion/error events with correct parallel_call_id
                    # so the frontend can match each event to the right agent card.
                    hitl_pause = False
                    for i, result in enumerate(results):
                        task = pydantic_tasks[i]
                        is_eval = task.recommended_agent and task.recommended_agent.upper() in ("EVALUATE", "QUERY", "WEB_SEARCH")

                        # Set parallel_call_id FIRST so ALL events in this iteration
                        # route to the correct frontend card (we're outside the
                        # parallel coroutine context, so the contextvar is unset).
                        _current_parallel_call_id.set(task.task_id)

                        if isinstance(result, Exception):
                            task.state = "failed"
                            task.error_message = str(result)
                            if task.recommended_agent and not is_eval:
                                await self._emit_granular_agent_event(
                                    task.recommended_agent, f"Error: {str(result)[:200]}", context_id,
                                    event_type="agent_error", metadata={"error": str(result)[:500]}
                                )
                        elif isinstance(result, dict):
                            if result.get("hitl_pause"):
                                hitl_pause = True
                                if result.get("output"):
                                    all_task_outputs.append(result["output"])
                            elif result.get("error"):
                                if task.recommended_agent and not is_eval:
                                    await self._emit_granular_agent_event(
                                        task.recommended_agent, f"Error: {result['error'][:200]}", context_id,
                                        event_type="agent_error", metadata={"error": result["error"][:500]}
                                    )
                            else:
                                if result.get("output"):
                                    all_task_outputs.append(result["output"])
                                # Emit agent_complete only for non-error, non-eval tasks.
                                # Eval/Query/WebSearch emit their own events inside their handlers.
                                if task.recommended_agent and not is_eval and not result.get("hitl_pause"):
                                    await self._emit_granular_agent_event(
                                        task.recommended_agent, f"{task.recommended_agent} completed", context_id,
                                        event_type="agent_complete"
                                    )

                        _current_parallel_call_id.set(None)
                        task.updated_at = datetime.now(timezone.utc)
                    
                    # If any task triggered HITL pause, save plan and return
                    if hitl_pause:
                        session_context.current_plan = plan
                        log_info(f"[Agent Mode] Saved plan for HITL resume (parallel tasks)")
                        await self._emit_plan_update(plan, context_id, reasoning=next_step.reasoning if next_step else None)
                        return all_task_outputs
                    
                    log_info(f"[Agent Mode] {len(pydantic_tasks)} parallel tasks completed")
                    # Emit plan update after parallel tasks complete
                    await self._emit_plan_update(plan, context_id, reasoning=next_step.reasoning if next_step else None)
                    
                else:
                    # ============================================
                    # SEQUENTIAL EXECUTION (single task)
                    # ============================================
                    task = pydantic_tasks[0]
                    task.state = "running"
                    task.updated_at = datetime.now(timezone.utc)
                    
                    try:
                        # Pass ALL accumulated outputs - smart context selection will pick the best one
                        # This is critical for HITL workflows where step N-1 may return a short response
                        # like "approved", but step N-2 has the actual data (e.g., invoice details)
                        previous_output = list(all_task_outputs) if all_task_outputs else None
                        
                        result = await self._execute_orchestrated_task(
                            task=task,
                            session_context=session_context,
                            context_id=context_id,
                            workflow=workflow,
                            user_message=user_message,
                            extract_text_fn=extract_text_from_response,
                            previous_task_outputs=previous_output
                        )
                        
                        if result.get("hitl_pause"):
                            if result.get("output"):
                                all_task_outputs.append(result["output"])
                            # Save plan for resume on next turn
                            session_context.current_plan = plan
                            log_info(f"[Agent Mode] Saved plan for HITL resume (sequential task)")
                            log_info(f"[Agent Mode] SAVED PLAN: {plan.model_dump_json(indent=2)}")
                            # VERIFICATION: Confirm the plan was actually set
                            log_info(f"[Agent Mode] VERIFY: session_context.current_plan is not None: {session_context.current_plan is not None}")
                            log_info(f"[Agent Mode] VERIFY: session_context.contextId: {session_context.contextId}")
                            return all_task_outputs
                        
                        if result.get("output"):
                            all_task_outputs.append(result["output"])
                        
                        # Emit agent_complete/agent_error based on task state from the plan
                        # Skip EVALUATE/QUERY tasks — they emit their own events
                        is_evaluate = task.recommended_agent and task.recommended_agent.upper() in ("EVALUATE", "QUERY", "WEB_SEARCH")
                        if task.state == "completed" and task.recommended_agent and not is_evaluate:
                            await self._emit_granular_agent_event(
                                task.recommended_agent, f"{task.recommended_agent} completed", context_id,
                                event_type="agent_complete"
                            )
                        elif task.state == "failed" and task.recommended_agent and not is_evaluate:
                            await self._emit_granular_agent_event(
                                task.recommended_agent, f"Error: {task.error_message or 'Unknown error'}"[:200], context_id,
                                event_type="agent_error", metadata={"error": (task.error_message or "Unknown error")[:500]}
                            )
                        
                    except Exception as e:
                        # IMPORTANT: Check if HITL was triggered before the error
                        # Sometimes the SSE stream errors out AFTER input_required was set
                        recommended_agent = task.recommended_agent
                        if session_context.pending_input_agent and session_context.pending_input_agent == recommended_agent:
                            log_info(f"[Agent Mode] Exception but HITL triggered - treating as input_required")
                            task.state = "input_required"
                            task.updated_at = datetime.now(timezone.utc)
                            # Save plan for resume
                            session_context.current_plan = plan
                            log_info(f"[Agent Mode] Saved plan for HITL resume (exception with pending input)")
                            return all_task_outputs
                        
                        task.state = "failed"
                        task.error_message = str(e)
                        log_error(f"[Agent Mode] Task execution error: {e}")
                        # Emit agent_error so frontend shows failure
                        if task.recommended_agent:
                            await self._emit_granular_agent_event(
                                task.recommended_agent, f"Error: {str(e)[:200]}", context_id,
                                event_type="agent_error", metadata={"error": str(e)[:500]}
                            )
                    
                    finally:
                        task.updated_at = datetime.now(timezone.utc)
                        # Emit plan update after each task state change
                        await self._emit_plan_update(plan, context_id, reasoning=next_step.reasoning if next_step else None)
                
            except Exception as e:
                log_error(f"[Agent Mode] Orchestration error: {e}")
                await self._emit_granular_agent_event(
                    "foundry-host-agent", f"Error in orchestration: {str(e)}", context_id,
                    event_type="agent_error", metadata={"error": str(e)}
                )
                break
        
        if iteration >= max_iterations:
            log_debug(f"[Agent Mode] Reached max iterations ({max_iterations})")
            await self._emit_granular_agent_event(
                "foundry-host-agent", "Maximum iterations reached, completing...", context_id,
                event_type="phase", metadata={"phase": "complete", "reason": "max_iterations"}
            )
        
        log_info(f"[Agent Mode] Complete: {len(all_task_outputs)} outputs, {iteration} iterations, {len(plan.tasks)} tasks")
        
        # Emit host token usage to frontend
        try:
            from service.websocket_streamer import get_websocket_streamer
            
            async def emit_host_tokens():
                streamer = await get_websocket_streamer()
                if streamer:
                    event_data = {
                        "agentName": "foundry-host-agent",
                        "tokenUsage": self.host_token_usage,
                        "state": "completed",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    await streamer._send_event("host_token_usage", event_data, context_id)
            
            asyncio.create_task(emit_host_tokens())
        except Exception:
            pass  # Don't let token emission failures break the flow
        
        return all_task_outputs
