"""
AI Foundry Agent with GitHub capabilities.
Uses the Responses API with native MCP tool support.
"""
import os
import time
import datetime
import asyncio
import logging
from typing import Optional, Dict

import httpx
from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

def _get_github_config():
    """Read GitHub config at call time (after dotenv loads)."""
    return (
        os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/"),
        os.getenv("GITHUB_PAT", ""),
    )

GITHUB_ALLOWED_TOOLS = [
    # === Issues ===
    "list_issues",
    "get_issue",
    "create_issue",
    "update_issue",
    "add_issue_comment",
    "list_issue_comments",
    # === Pull Requests ===
    "list_pull_requests",
    "get_pull_request",
    "create_pull_request",
    "merge_pull_request",
    "list_pull_request_reviews",
    # === Repositories ===
    "get_repository",
    "list_repositories",
    "list_branches",
    "list_commits",
    # === Search ===
    "search_issues",
    "search_code",
    # === Labels & Milestones ===
    "list_labels",
    "create_label",
    "list_milestones",
]


class FoundryGitHubAgent:
    """AI Foundry Agent with GitHub capabilities via Responses API."""

    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self._client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
        self._response_ids: Dict[str, str] = {}
        self.last_token_usage: Optional[Dict[str, int]] = None
        self._mcp_url, self._github_pat = _get_github_config()
        mcp_headers = {}
        if self._github_pat:
            mcp_headers["Authorization"] = f"Bearer {self._github_pat}"
        self._mcp_tool_config = {
            "type": "mcp",
            "server_label": "GitHub",
            "server_url": self._mcp_url,
            "require_approval": "never",
            "allowed_tools": GITHUB_ALLOWED_TOOLS,
            **({"headers": mcp_headers} if mcp_headers else {}),
        }

    def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is None:
            if "services.ai.azure.com" in self.endpoint:
                resource_name = self.endpoint.split("//")[1].split(".")[0]
                openai_endpoint = f"https://{resource_name}.openai.azure.com/openai/v1/"
            else:
                openai_endpoint = (
                    self.endpoint
                    if self.endpoint.endswith("/openai/v1/")
                    else f"{self.endpoint.rstrip('/')}/openai/v1/"
                )
            token_provider = get_bearer_token_provider(
                self.credential, "https://cognitiveservices.azure.com/.default",
            )
            self._client = AsyncAzureOpenAI(
                base_url=openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="preview",
            )
        return self._client

    async def create_agent(self) -> None:
        if self._initialized:
            return
        logger.info("Initializing GitHub agent (Responses API)...")
        logger.info(f"   MCP Server: {self._mcp_url}")
        logger.info(f"   GitHub PAT: {'configured' if self._github_pat else 'NOT SET - MCP calls will fail'}")
        try:
            headers = {}
            if self._github_pat:
                headers["Authorization"] = f"Bearer {self._github_pat}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._mcp_url, headers=headers)
                logger.info(f"MCP Server status: {response.status_code}")
        except Exception as e:
            logger.warning(f"MCP Server connectivity test failed: {e} (continuing anyway)")
        self._get_client()
        self._initialized = True

    def _get_agent_instructions(self) -> str:
        return f"""You are a GitHub assistant that helps manage issues, pull requests, and repositories.

Current date: {datetime.datetime.now().isoformat()}

## TOOL HINTS

When users ask about GitHub data, use the appropriate tools:
- Issues: list_issues, get_issue, create_issue, update_issue, add_issue_comment
- Pull Requests: list_pull_requests, get_pull_request, create_pull_request, merge_pull_request
- Repositories: get_repository, list_repositories, list_branches, list_commits
- Search: search_issues, search_code
- Labels: list_labels, create_label
- Milestones: list_milestones

## KEY RULES

1. **USE THE DATA PROVIDED** - Don't ask for info already in context
2. **MINIMIZE TOOL CALLS** - Combine queries when possible
3. **Be specific with search** - Use filters (state, labels, assignee) to narrow results
4. **Format output clearly** - Use markdown tables for lists, link to issues/PRs by number

## ISSUE vs PULL REQUEST

- **Issue**: A bug report, feature request, or task. Use create_issue.
- **Pull Request**: A code change proposal. Use create_pull_request (requires head/base branches).

## Error Reporting (CRITICAL)

If you CANNOT complete the requested task — due to rate limits, API errors, missing data,
authentication failures, or any other reason — you MUST start your response with "Error:".

Examples:
- "Error: Rate limit exceeded. Please try again later."
- "Error: Authentication failed — invalid credentials."
- "Error: Could not complete the request due to a service outage."

Do NOT write a polite explanation without the "Error:" prefix. The system uses this prefix
to detect failures. Without it, the task is marked as successful even though it failed.

## NEEDS_INPUT - Human-in-the-Loop

Use NEEDS_INPUT to pause and ask the user a question:

```NEEDS_INPUT
Your question here
```END_NEEDS_INPUT

Use when:
1. Repository owner/name is not clear from context
2. The user request is ambiguous
3. The workflow says "HITL REQUIRED"
"""

    async def create_session(self) -> str:
        return f"session_{int(time.time())}_{os.urandom(4).hex()}"

    async def run_conversation_stream(self, session_id: str, user_message: str):
        if not self._initialized:
            await self.create_agent()

        client = self._get_client()
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        kwargs = {
            "model": model,
            "instructions": self._get_agent_instructions(),
            "input": [{"role": "user", "content": user_message}],
            "tools": [self._mcp_tool_config],
            "stream": True,
            "max_output_tokens": 4000,
        }
        if session_id in self._response_ids:
            kwargs["previous_response_id"] = self._response_ids[session_id]

        retry_count = 0
        max_retries = 3
        while retry_count <= max_retries:
            try:
                stream_start = time.time()
                response = await client.responses.create(**kwargs)
                text_chunks = []
                tool_calls_seen = set()
                mcp_failures = []
                tool_call_times = {}

                async for event in response:
                    event_type = getattr(event, 'type', None)

                    if event_type == "response.output_text.delta":
                        text_chunks.append(event.delta)
                    elif event_type == "response.mcp_call.in_progress":
                        tool_name = getattr(event, 'name', 'mcp_tool')
                        if tool_name not in tool_calls_seen:
                            tool_calls_seen.add(tool_name)
                            tool_call_times[tool_name] = time.time()
                            yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"
                    elif event_type == "response.mcp_call.completed":
                        pass
                    elif event_type == "response.mcp_call.failed":
                        tool_name = getattr(event, 'name', None) or getattr(event, 'item_id', 'mcp_tool')
                        mcp_failures.append(tool_name)
                    elif event_type == "response.failed":
                        resp = getattr(event, 'response', None)
                        error_obj = getattr(resp, 'error', None) if resp else None
                        yield f"Error: {getattr(error_obj, 'message', 'Unknown error') if error_obj else 'Unknown error'}"
                        return
                    elif event_type == "response.output_item.added":
                        item = getattr(event, 'item', None)
                        if item and getattr(item, 'type', None) in ("mcp_call", "mcp_tool_call"):
                            tool_name = getattr(item, 'name', None) or getattr(item, 'tool_name', 'mcp_tool')
                            if tool_name not in tool_calls_seen:
                                tool_calls_seen.add(tool_name)
                                tool_call_times[tool_name] = time.time()
                                yield f"\U0001f6e0\ufe0f Remote agent executing: {self._get_tool_description(tool_name)}"
                    elif event_type in ("response.completed", "response.done"):
                        resp = getattr(event, 'response', None)
                        if resp:
                            usage = getattr(resp, 'usage', None)
                            if usage:
                                self.last_token_usage = {
                                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0),
                                    "completion_tokens": getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0),
                                    "total_tokens": getattr(usage, 'total_tokens', 0),
                                }
                            resp_id = getattr(resp, 'id', None)
                            if resp_id:
                                self._response_ids[session_id] = resp_id

                if text_chunks:
                    full_text = "".join(text_chunks)
                    if mcp_failures:
                        yield f"Error: MCP tool(s) failed ({', '.join(mcp_failures)}). {full_text}"
                    else:
                        yield full_text
                else:
                    yield "Error: Agent completed but no response text was generated"
                return

            except Exception as e:
                error_str = str(e).lower()
                if "rate_limit" in error_str or "429" in error_str or "too many requests" in error_str:
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff = min(15 * (2 ** retry_count), 60)
                        yield f"Rate limit hit - retrying in {backoff}s..."
                        await asyncio.sleep(backoff)
                        continue
                    yield f"Error: Rate limit exceeded after {max_retries} retries"
                else:
                    yield f"Error: {e}"
                return

    def _get_tool_description(self, tool_name: str) -> str:
        descriptions = {
            "list_issues": "Listing GitHub issues",
            "get_issue": "Getting issue details",
            "create_issue": "Creating GitHub issue",
            "update_issue": "Updating GitHub issue",
            "add_issue_comment": "Adding issue comment",
            "list_issue_comments": "Listing issue comments",
            "list_pull_requests": "Listing pull requests",
            "get_pull_request": "Getting PR details",
            "create_pull_request": "Creating pull request",
            "merge_pull_request": "Merging pull request",
            "list_pull_request_reviews": "Listing PR reviews",
            "get_repository": "Getting repository info",
            "list_repositories": "Listing repositories",
            "list_branches": "Listing branches",
            "list_commits": "Listing commits",
            "search_issues": "Searching issues",
            "search_code": "Searching code",
            "list_labels": "Listing labels",
            "create_label": "Creating label",
            "list_milestones": "Listing milestones",
        }
        return descriptions.get(tool_name, tool_name.replace("_", " ").title())

    async def run_conversation(self, session_id: str, user_message: str) -> str:
        return "\n".join([r async for r in self.run_conversation_stream(session_id, user_message)])

    async def chat(self, session_id: str, user_message: str) -> str:
        return await self.run_conversation(session_id, user_message)
