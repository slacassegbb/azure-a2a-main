import json
from typing import Any, AsyncIterable, Optional
from google.adk.agents.llm_agent import LlmAgent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# --- Sentiment Analysis Tool ---
def detect_sentiment(text: str) -> dict[str, Any]:
    text_lower = text.lower()
    if any(word in text_lower for word in ["happy", "great", "good", "love", "excellent", "awesome", "fantastic"]):
        sentiment = "positive"
    elif any(word in text_lower for word in ["sad", "bad", "terrible", "hate", "awful", "horrible", "angry", "fraud"]):
        sentiment = "negative"
    else:
        sentiment = "neutral"
    return {
        "sentiment": sentiment,
        "input": text,
        "personalized_message": personalize_experience(sentiment, text)
    }

def personalize_experience(sentiment: str, context: str) -> str:
    if sentiment == "positive":
        return "We're glad you're having a great experience! If there's anything else we can do for you, let us know."
    elif sentiment == "negative":
        return "We're sorry to hear that. We'll do our best to help and improve your experience. Please tell us more."
    else:
        return "Thank you for your feedback. If you have any specific requests or feelings to share, we're here to listen."

def format_sentiment_response(sentiment: str, context: str, personalized_message: str) -> str:
    # Compose a warm, customer-focused message without mentioning the agent
    return (
        f"We detected a {sentiment} sentiment regarding the issue you raised: '{context}'. "
        f"Here's a personalized message for you:\n\n"
        f"\"{personalized_message}\"\n\n"
        f"Let us know how we can help further!"
    )

class SentimentAnalysisAgent:
    """An agent that analyzes sentiment and personalizes the customer experience."""

    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']

    def __init__(self):
        self._agent = self._build_agent()
        self._user_id = 'remote_agent'
        self._runner = Runner(
            app_name=self._agent.name,
            agent=self._agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    def get_processing_message(self) -> str:
        return 'Analyzing sentiment and personalizing your experience...'

    def _build_agent(self) -> LlmAgent:
        """Builds the LLM agent for sentiment analysis."""
        return LlmAgent(
            model='gemini-2.0-flash-001',
            name='sentiment_analysis_agent',
            description=(
                'This agent determines the sentiment of a customer given context, '
                'and personalizes the experience based on sentiment and context.'
            ),
            instruction="""
You are a sentiment analysis agent. Your job is to:
- Analyze the sentiment (positive, negative, or neutral) of the user's message and context.
- Return a user-facing message that:
  - Clearly states the detected sentiment in a natural way (e.g., 'The Sentiment Analysis Agent identified the sentiment as ... regarding ...').
  - Includes an empathetic, context-aware message.
  - Optionally, ends with a prompt for further assistance.
- Example output:
  The Sentiment Analysis Agent identified the sentiment as neutral regarding the issue you raised about credit card fraud. Here's the personalized message:
  "Thank you for your feedback. If you have any specific requests or feelings to share, we're here to listen."
  Let me know how I can assist further with this matter.

Always be concise, friendly, and context-aware.
""",
            tools=[detect_sentiment],
        )

    async def stream(self, query, session_id) -> AsyncIterable[dict[str, Any]]:
        print(f"[GOOGLE ADK DEBUG] ========== PAYLOAD DEBUG ==========")
        print(f"[GOOGLE ADK DEBUG] Session ID: {session_id}")
        print(f"[GOOGLE ADK DEBUG] Query type: {type(query)}")
        print(f"[GOOGLE ADK DEBUG] Query length: {len(query)} characters")
        print(f"[GOOGLE ADK DEBUG] Query content (first 1000 chars):")
        print(f"[GOOGLE ADK DEBUG] {query[:1000]}")
        if len(query) > 1000:
            print(f"[GOOGLE ADK DEBUG] ... (truncated, total length: {len(query)})")
        print(f"[GOOGLE ADK DEBUG] ==========================================")

        session = await self._runner.session_service.get_session(
            app_name=self._agent.name,
            user_id=self._user_id,
            session_id=session_id,
        )
        content = types.Content(
            role='user', parts=[types.Part.from_text(text=query)]
        )
        if session is None:
            session = await self._runner.session_service.create_session(
                app_name=self._agent.name,
                user_id=self._user_id,
                state={},
                session_id=session_id,
            )
        async for event in self._runner.run_async(
            user_id=self._user_id, session_id=session.id, new_message=content
        ):
            if event.is_final_response():
                response = ''
                # Try to extract the function/tool response if present
                if (
                    event.content
                    and event.content.parts
                    and any(
                        [getattr(p, 'function_response', None) for p in event.content.parts]
                    )
                ):
                    # Use the tool response to format the final message
                    tool_result = next(
                        p.function_response.model_dump()
                        for p in event.content.parts
                        if getattr(p, 'function_response', None)
                    )
                    if isinstance(tool_result, str):
                        tool_result = json.loads(tool_result)
                    sentiment = tool_result.get('sentiment', 'neutral')
                    context = tool_result.get('input', query)
                    personalized_message = tool_result.get('personalized_message', '')
                    response = format_sentiment_response(sentiment, context, personalized_message)
                elif (
                    event.content
                    and event.content.parts
                    and event.content.parts[0].text
                ):
                    response = '\n'.join(
                        [p.text for p in event.content.parts if p.text]
                    )
                yield {
                    'is_task_complete': True,
                    'content': response,
                }
            else:
                yield {
                    'is_task_complete': False,
                    'updates': self.get_processing_message(),
                }
