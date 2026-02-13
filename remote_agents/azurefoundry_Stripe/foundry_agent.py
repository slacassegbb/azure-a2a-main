"""
AI Foundry Agent implementation with Stripe Payment Processing Capabilities.
Uses AgentsClient directly for Azure AI Foundry with Stripe MCP integration.

IMPORTANT: QUOTA REQUIREMENTS FOR AZURE AI FOUNDRY AGENTS
=========================================================

Based on Microsoft support documentation, Azure AI Foundry agents require a 
MINIMUM of 20,000 TPM (Tokens Per Minute) to function properly without rate limiting.
"""
import os
import asyncio
import logging
import json
from typing import Optional, Dict, Any
import httpx

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent, ListSortOrder, ToolSet, McpTool, ToolApproval
)
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


# Stripe MCP Server URL (deployed on Azure Container Apps)
STRIPE_MCP_URL = os.getenv(
    "STRIPE_MCP_URL", 
    "https://mcp-stripe.ambitioussky-6c709152.westus2.azurecontainerapps.io/sse"
)


class FoundryStripeAgent:
    """
    AI Foundry Agent with Stripe Payment Processing capabilities.
    Uses AgentsClient directly for the new SDK version with McpTool integration.
    """
    
    def __init__(self):
        self.endpoint = os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"]
        self.credential = DefaultAzureCredential()
        self.agent: Optional[Agent] = None
        self.threads: Dict[str, str] = {}
        self._agents_client = None
        self._mcp_tool = None
        self._mcp_tool_resources = None
        self.last_token_usage: Optional[Dict[str, int]] = None
        
    def _get_agents_client(self) -> AgentsClient:
        """Get a cached AgentsClient instance."""
        if self._agents_client is None:
            self._agents_client = AgentsClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._agents_client
        
    async def create_agent(self) -> Agent:
        """Create the AI Foundry agent with Stripe capabilities using McpTool."""
        if self.agent:
            logger.info("Agent already exists, returning existing instance")
            return self.agent
        
        logger.info("🚀 CREATING NEW AZURE FOUNDRY STRIPE AGENT...")
        
        # Create McpTool with Azure's native MCP integration
        logger.info("🔧 CREATING McpTool CONNECTION...")
        logger.info(f"   MCP Server: {STRIPE_MCP_URL}")
        
        tools = []
        
        try:
            # Test MCP server connectivity using health endpoint
            logger.info("🧪 TESTING MCP SERVER CONNECTIVITY...")
            async def test_mcp_basic():
                try:
                    # Test base URL (returns server info)
                    base_url = STRIPE_MCP_URL.rstrip('/sse')
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(base_url)
                        logger.info(f"   MCP Server Response: {response.status_code}")
                        logger.info(f"   Response Content (first 100 chars): {response.text[:100]}")
                        if response.status_code == 200:
                            logger.info("✅ MCP Server connectivity test PASSED")
                            return True
                        else:
                            logger.error(f"❌ MCP Server returned status: {response.status_code}")
                            return False
                except Exception as e:
                    logger.error(f"   MCP Server Test FAILED: {e}")
                    return False
            
            await test_mcp_basic()
            
            # Create MCP tool with all Stripe tools
            # NOTE: Stripe MCP tools do NOT have a prefix (e.g., "list_customers" not "stripe_list_customers")
            logger.info("🔧 CREATING McpTool OBJECT...")
            mcp_tool = McpTool(
                server_label="Stripe",
                server_url=STRIPE_MCP_URL,
                allowed_tools=[
                    # Customer Management
                    "create_customer",
                    "list_customers",
                    # Products & Prices
                    "create_product",
                    "list_products",
                    "create_price",
                    "list_prices",
                    # Payment Links
                    "create_payment_link",
                    # Invoices
                    "create_invoice",
                    "list_invoices",
                    "create_invoice_item",
                    "finalize_invoice",
                    # Balance & Payments
                    "retrieve_balance",
                    "create_refund",
                    "list_payment_intents",
                    # Subscriptions
                    "list_subscriptions",
                    "cancel_subscription",
                    "update_subscription",
                    # Coupons & Disputes
                    "list_coupons",
                    "create_coupon",
                    "update_dispute",
                    "list_disputes",
                    # Documentation
                    "search_stripe_documentation"
                ]
            )
            
            # Store the mcp_tool for resources access
            self._mcp_tool = mcp_tool
            logger.info("✅ McpTool object created successfully")

            # Set approval mode to "never" - MCP tools execute without human approval
            mcp_tool.set_approval_mode("never")
            logger.info("✅ Set approval mode to 'never'")
            
            # Set headers for MCP communication
            mcp_tool.update_headers("Content-Type", "application/json")
            mcp_tool.update_headers("User-Agent", "Azure-AI-Foundry-Agent")
            mcp_tool.update_headers("Accept", "application/json, text/event-stream")
            logger.info("✅ Set MCP headers")
            
            # Get tool definitions from MCP
            tools = list(mcp_tool.definitions)
            
            # Store MCP tool resources - needed for runs.create()
            self._mcp_tool_resources = mcp_tool.resources
            
            logger.info(f"🔍 MCP TOOL DETAILS:")
            logger.info(f"   Tools count: {len(tools)}")
            logger.info(f"   MCP Tool resources for run creation: {type(self._mcp_tool_resources)}")
            logger.info("✅ Added Stripe MCP server integration using McpTool")
            
        except Exception as e:
            logger.error(f"❌ FAILED TO CREATE MCP TOOL: {e}")
            import traceback
            logger.error(f"   Full traceback: {traceback.format_exc()}")
            logger.warning("⚠️ Continuing without MCP tools due to connection failure")
        
        # Get model deployment name
        model = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        # Stripe-specific instructions
        instructions = self._get_agent_instructions()
        
        logger.info(f"Creating Stripe agent with model: {model}")
        
        # Use AgentsClient to create agent with McpTool
        agents_client = self._get_agents_client()
        
        self.agent = agents_client.create_agent(
            model=model,
            name="AI Foundry Stripe Agent",
            instructions=instructions,
            tools=tools,
        )
        
        logger.info(f"✅ Created Stripe agent: {self.agent.id}")
        logger.info(f"   Tools: {len(tools)} definitions")
        return self.agent
    
    def _get_agent_instructions(self) -> str:
        """Get the agent instructions for Stripe payment processing."""
        return """You are an expert Stripe payment processing assistant. You help users manage their Stripe account.

## Your Capabilities

You have access to Stripe MCP tools for:
- **Customer Management**: create_customer, list_customers
- **Invoices**: create_invoice, list_invoices, create_invoice_item, finalize_invoice
- **Balance & Payments**: retrieve_balance, create_refund, list_payment_intents
- **Products & Prices**: create_product, list_products, create_price, list_prices (rarely needed)

## KEY RULES:

1. **USE THE DATA PROVIDED** - Don't ask for info already in the context
2. **Be MINIMAL** - Use the FEWEST tool calls possible
3. **Don't ask for confirmation** - If you have the data, just do the task
4. **ALWAYS PROVIDE A SUMMARY** - After completing tool calls, write a brief summary of what you did

## CRITICAL: CREATING INVOICES (3 STEPS ONLY!)

⚠️ DO NOT create products or prices for invoices! Use amount directly.

**Step 1: Find or create customer**
```
list_customers with: {"email": "customer@example.com"}
```
If not found: create_customer with email

**Step 2: Create invoice + add items**
```
create_invoice with: {"customer": "cus_xxxxx"}
```
Then for EACH line item:
```
create_invoice_item with: {"invoice": "in_xxxxx", "amount": 32000, "description": "Item"}
```
- amount is in CENTS (100 = $1.00, so $320 = 32000)
- DO NOT use create_product or create_price!

**Step 3: Finalize (optional)**
```
finalize_invoice with: {"invoice": "in_xxxxx"}
```

TOTAL: 3-5 tool calls max for an invoice!

**After completing the invoice, ALWAYS write a summary like:**
"✅ Created invoice [invoice_id] for [customer_name] with [X] line items totaling $[amount]"

## ASKING FOR INPUT:

Only if information is genuinely MISSING:
```
NEEDS_INPUT: Your specific question here
```
"""
    
    async def create_thread(self) -> str:
        """Create a new conversation thread."""
        agents_client = self._get_agents_client()
        thread = agents_client.threads.create()
        logger.info(f"Created new thread: {thread.id}")
        return thread.id
    
    async def add_message(self, thread_id: str, content: str, role: str = "user"):
        """Add a message to a thread."""
        agents_client = self._get_agents_client()
        message = agents_client.messages.create(
            thread_id=thread_id,
            role=role,
            content=content,
        )
        logger.info(f"Added {role} message to thread {thread_id}")
        return message

    async def run_conversation_stream(self, thread_id: str, user_message: str):
        """Run conversation and yield responses."""
        logger.info(f"🚀 STARTING CONVERSATION STREAM")
        logger.info(f"   Thread ID: {thread_id}")
        logger.warning(f"📥 FULL INCOMING CONTEXT (length={len(user_message)} chars):")
        logger.warning(f"{user_message}")
        
        if not self.agent:
            await self.create_agent()

        await self.add_message(thread_id, user_message)
        
        client = self._get_agents_client()
        
        # Create run with MCP tool resources
        mcp_tool = self._mcp_tool
        if mcp_tool and hasattr(mcp_tool, 'resources'):
            logger.info("🔧 Creating run with MCP tool_resources")
            run = client.runs.create(
                thread_id=thread_id,
                agent_id=self.agent.id,
                tool_resources=mcp_tool.resources,
                truncation_strategy={"type": "last_messages", "last_messages": 4}
            )
        else:
            logger.info("Creating run without MCP tool_resources")
            run = client.runs.create(
                thread_id=thread_id,
                agent_id=self.agent.id,
                truncation_strategy={"type": "last_messages", "last_messages": 4}
            )
        
        logger.info(f"   Run created: {run.id}")
        
        # Check if run failed immediately (before the while loop)
        if run.status == "failed":
            logger.error(f"❌ RUN FAILED IMMEDIATELY ON CREATION!")
            logger.error(f"   Run ID: {run.id}")
            logger.error(f"   Last error: {run.last_error}")
            yield f"❌ **Run Failed Immediately:** {run.last_error}"
            return
        
        max_iterations = 25
        iterations = 0
        retry_count = 0
        max_retries = 3
        tool_calls_yielded = set()

        while run.status in ["queued", "in_progress", "requires_action"] and iterations < max_iterations:
            iterations += 1
            logger.info(f"   🔄 Iteration {iterations}: run.status = {run.status}")
            
            # Use adaptive polling: start fast, slow down to reduce API calls and token usage
            # First 3 polls: 2s (fast startup)
            # Next 5 polls: 3s (moderate)
            # After that: 5s (conserve TPM)
            if iterations <= 3:
                poll_interval = 2
            elif iterations <= 8:
                poll_interval = 3
            else:
                poll_interval = 5
            
            await asyncio.sleep(poll_interval)
            
            # Check for tool calls
            try:
                run_steps = client.run_steps.list(thread_id, run.id)
                for run_step in run_steps:
                    step_id = getattr(run_step, 'id', f'step_{iterations}')
                    if (hasattr(run_step, "step_details") and
                        hasattr(run_step.step_details, "type") and
                        run_step.step_details.type == "tool_calls" and
                        hasattr(run_step.step_details, "tool_calls")):
                        for idx, tool_call in enumerate(run_step.step_details.tool_calls):
                            tool_call_id = getattr(tool_call, 'id', f'{step_id}_call_{idx}')
                            if tool_call_id not in tool_calls_yielded:
                                tool_type = getattr(tool_call, 'type', 'unknown')
                                yield f"🛠️ Remote agent executing: {tool_type}"
                                tool_calls_yielded.add(tool_call_id)
            except Exception as e:
                logger.warning(f"   ⚠️ Error getting run steps: {e}")

            try:
                run = client.runs.get(thread_id=thread_id, run_id=run.id)
            except Exception as e:
                if "rate limit" in str(e).lower() or "429" in str(e):
                    retry_count += 1
                    if retry_count <= max_retries:
                        backoff_time = min(15 * (2 ** retry_count), 45)
                        logger.warning(f"🔄 Rate limit on polling - retry {retry_count}/{max_retries} after {backoff_time}s")
                        await asyncio.sleep(backoff_time)
                        continue
                    else:
                        yield "Error: Rate limit exceeded, please try again later"
                        return
                else:
                    yield f"Error: {str(e)}"
                    return

            if run.status == "failed":
                logger.error(f"❌ RUN FAILED!")
                logger.error(f"   Run ID: {run.id}")
                logger.error(f"   Last error: {run.last_error}")
                
                # Check for rate limit error and retry with exponential backoff
                error_code = None
                error_message = None
                if run.last_error:
                    if hasattr(run.last_error, 'code'):
                        error_code = run.last_error.code
                    if hasattr(run.last_error, 'message'):
                        error_message = run.last_error.message
                    
                    # CHECK FOR RATE LIMIT ERROR - Retry with exponential backoff
                    if error_code == 'rate_limit_exceeded' or (error_message and 'rate limit' in error_message.lower()):
                        logger.warning(f"🔄 RATE LIMIT DETECTED - Implementing retry logic")
                        retry_count += 1
                        if retry_count <= max_retries:
                            # Exponential backoff: 15s, 30s, 60s
                            backoff_time = min(15 * (2 ** retry_count), 60)
                            logger.warning(f"   Retry {retry_count}/{max_retries} after {backoff_time}s backoff")
                            yield f"⏳ Rate limit hit - retrying in {backoff_time}s (attempt {retry_count}/{max_retries})..."
                            await asyncio.sleep(backoff_time)
                            
                            # Reset run and continue the loop
                            logger.info(f"🔄 Retrying run creation after rate limit backoff...")
                            if mcp_tool and hasattr(mcp_tool, 'resources'):
                                run = client.runs.create(
                                    thread_id=thread_id,
                                    agent_id=self.agent.id,
                                    tool_resources=mcp_tool.resources,
                                    truncation_strategy={"type": "last_messages", "last_messages": 8}
                                )
                            else:
                                run = client.runs.create(
                                    thread_id=thread_id,
                                    agent_id=self.agent.id,
                                    truncation_strategy={"type": "last_messages", "last_messages": 8}
                                )
                            logger.info(f"   New run created: {run.id}")
                            iterations = 0  # Reset iteration counter for the new run
                            continue  # Continue the while loop with the new run
                        else:
                            logger.error(f"❌ Max retries ({max_retries}) exceeded for rate limit")
                            yield f"❌ Rate limit exceeded after {max_retries} retries - please wait and try again later"
                            return
                
                yield f"❌ **Run Failed:** {run.last_error}"
                return

            if run.status == "requires_action":
                logger.info(f"🔧 RUN REQUIRES ACTION")
                # MCP tools with approval_mode="never" should auto-execute
                # But if we get here, just wait for it to process
                await asyncio.sleep(2)

        # Get final response
        if run.status == "completed":
            # Extract token usage
            if hasattr(run, 'usage') and run.usage:
                self.last_token_usage = {
                    "prompt_tokens": run.usage.prompt_tokens,
                    "completion_tokens": run.usage.completion_tokens,
                    "total_tokens": run.usage.total_tokens
                }
                logger.warning(f"📊 Token usage: {self.last_token_usage}")

            # LOG ALL RUN STEPS TO DEBUG TOOL CALLS
            try:
                logger.info("🔍 RETRIEVING RUN STEPS TO DEBUG TOOL CALLS...")
                run_steps = list(client.run_steps.list(thread_id, run.id))
                logger.warning(f"📋 Total run steps: {len(run_steps)}")

                for i, step in enumerate(run_steps):
                    logger.warning(f"  Step {i+1}: type={step.type}, status={step.status}")
                    if hasattr(step, 'step_details'):
                        details = step.step_details
                        logger.warning(f"    Details type: {type(details)}")

                        # Log tool calls
                        if hasattr(details, 'tool_calls'):
                            for j, tool_call in enumerate(details.tool_calls):
                                logger.warning(f"    Tool call {j+1}:")
                                logger.warning(f"      Type: {tool_call.type if hasattr(tool_call, 'type') else 'unknown'}")
                                if hasattr(tool_call, 'function'):
                                    logger.warning(f"      Function: {tool_call.function.name if hasattr(tool_call.function, 'name') else 'unknown'}")
                                    logger.warning(f"      Arguments: {tool_call.function.arguments if hasattr(tool_call.function, 'arguments') else 'none'}")
                                if hasattr(tool_call, 'output'):
                                    output_preview = str(tool_call.output)[:200] if tool_call.output else 'none'
                                    logger.warning(f"      Output: {output_preview}")
            except Exception as e:
                logger.error(f"❌ Error retrieving run steps: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
            
            # Get messages
            try:
                messages_list = list(client.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING))
                logger.info(f"📨 Retrieved {len(messages_list)} messages from thread")

                # Log all messages for debugging
                for i, msg in enumerate(messages_list):
                    logger.info(f"   Message {i}: role={msg.role}, content_parts={len(msg.content) if hasattr(msg, 'content') else 0}")

                found_response = False
                for msg in messages_list:
                    logger.info(f"   Checking message with role: {msg.role}")
                    if msg.role == "assistant":
                        logger.info(f"   Assistant message has {len(msg.content)} content parts")
                        for idx, content in enumerate(msg.content):
                            logger.info(f"   Content {idx}: type={type(content)}, hasText={hasattr(content, 'text')}")
                            if hasattr(content, 'text') and hasattr(content.text, 'value'):
                                response_text = content.text.value
                                logger.info(f"✅ Found response text ({len(response_text)} chars)")
                                yield response_text
                                found_response = True
                            elif hasattr(content, 'text'):
                                logger.warning(f"   Text object exists but no 'value' attribute: {dir(content.text)}")
                            else:
                                logger.warning(f"   Content has no text attribute. Attributes: {dir(content)}")
                        break

                if not found_response:
                    logger.error("❌ No assistant response text found in messages")
                    yield "Error: Agent completed but no response text was found"

            except Exception as e:
                logger.error(f"❌ Error extracting messages: {e}")
                logger.error(f"   Exception type: {type(e)}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                yield f"Error extracting response: {str(e)}"
        else:
            logger.error(f"❌ RUN ENDED WITH NON-COMPLETED STATUS: {run.status}")
            logger.error(f"   Run ID: {run.id}")
            logger.error(f"   Thread ID: {thread_id}")

            # Log detailed error information
            if hasattr(run, 'last_error') and run.last_error:
                logger.error(f"   Last Error: {run.last_error}")

            if hasattr(run, 'incomplete_details') and run.incomplete_details:
                logger.error(f"   Incomplete Details: {run.incomplete_details}")

            # Log token usage if available
            if hasattr(run, 'usage') and run.usage:
                logger.error(f"   Token Usage: prompt={run.usage.prompt_tokens}, completion={run.usage.completion_tokens}, total={run.usage.total_tokens}")

            # Log all run attributes for debugging
            logger.error(f"   Run attributes: {dir(run)}")

            # Try to get run steps to see what actually happened
            try:
                run_steps = client.run_steps.list(thread_id, run.id)
                logger.error(f"   Run steps count: {len(list(run_steps))}")
                for step in run_steps:
                    logger.error(f"     Step {step.id}: status={step.status}, type={step.type}")
                    if hasattr(step, 'step_details'):
                        logger.error(f"       Details: {step.step_details}")
            except Exception as e:
                logger.error(f"   Could not retrieve run steps: {e}")

            yield f"Run ended with status: {run.status}"

    async def run_conversation(self, thread_id: str, user_message: str) -> str:
        """Non-streaming version - collects all responses."""
        responses = []
        try:
            async for response in self.run_conversation_stream(thread_id, user_message):
                logger.info(f"📥 Collected response chunk ({len(response)} chars): {response[:100]}...")
                responses.append(response)
            logger.info(f"✅ Collected {len(responses)} total response chunks")
            final_response = "\n".join(responses)
            logger.info(f"📤 Returning final response ({len(final_response)} chars): {final_response[:200]}...")
            return final_response
        except Exception as e:
            logger.error(f"❌ Error in run_conversation: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            raise

    async def chat(self, thread_id: str, user_message: str) -> str:
        """Alias for run_conversation - for executor compatibility."""
        return await self.run_conversation(thread_id, user_message)

