"""
Simple token logging for QuickBooks agent.
Logs all incoming messages, tool calls, and token usage to a file.
"""
import os
import json
from datetime import datetime

# Create log file in the agent directory
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "quickbooks_tokens.log")

def _estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token"""
    if not text:
        return 0
    return len(text) // 4

def _write_log(entry: str):
    """Append entry to log file"""
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")

def log_separator(title: str = ""):
    """Log a visual separator"""
    separator = f"\n{'='*80}\n"
    if title:
        separator += f"  {title}\n"
        separator += f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    separator += f"{'='*80}\n"
    _write_log(separator)

def log_incoming_request(thread_id: str, user_message: str, context_id: str = None):
    """Log the incoming request from the host orchestrator"""
    log_separator(f"NEW REQUEST - Thread: {thread_id}")
    
    char_count = len(user_message)
    token_estimate = _estimate_tokens(user_message)
    
    entry = f"""
📥 INCOMING REQUEST
   Context ID: {context_id or 'N/A'}
   Thread ID: {thread_id}
   Message Length: {char_count:,} chars (~{token_estimate:,} tokens)
   
   FULL MESSAGE:
   {'-'*60}
{user_message}
   {'-'*60}
"""
    _write_log(entry)
    print(f"📝 TOKEN_LOG: Incoming request - {char_count:,} chars (~{token_estimate:,} tokens)")

def log_thread_message(thread_id: str, role: str, content: str):
    """Log a message being added to the thread"""
    char_count = len(content) if content else 0
    token_estimate = _estimate_tokens(content)
    
    entry = f"""
📨 THREAD MESSAGE ({role.upper()})
   Thread ID: {thread_id}
   Length: {char_count:,} chars (~{token_estimate:,} tokens)
   
   CONTENT:
   {'-'*60}
{content[:2000]}{'... [TRUNCATED]' if len(content) > 2000 else ''}
   {'-'*60}
"""
    _write_log(entry)
    print(f"📝 TOKEN_LOG: Thread msg ({role}) - {char_count:,} chars (~{token_estimate:,} tokens)")

def log_tool_call(tool_name: str, tool_args: dict, thread_id: str = None):
    """Log a tool call"""
    args_str = json.dumps(tool_args, indent=2) if tool_args else "{}"
    char_count = len(args_str)
    token_estimate = _estimate_tokens(args_str)
    
    entry = f"""
🔧 TOOL CALL: {tool_name}
   Thread ID: {thread_id or 'N/A'}
   Args Length: {char_count:,} chars (~{token_estimate:,} tokens)
   
   ARGUMENTS:
   {'-'*60}
{args_str[:1000]}{'... [TRUNCATED]' if len(args_str) > 1000 else ''}
   {'-'*60}
"""
    _write_log(entry)
    print(f"📝 TOKEN_LOG: Tool call {tool_name} - {char_count:,} chars (~{token_estimate:,} tokens)")

def log_tool_result(tool_name: str, result: str, thread_id: str = None):
    """Log a tool result"""
    result_str = str(result) if result else ""
    char_count = len(result_str)
    token_estimate = _estimate_tokens(result_str)
    
    entry = f"""
📤 TOOL RESULT: {tool_name}
   Thread ID: {thread_id or 'N/A'}
   Result Length: {char_count:,} chars (~{token_estimate:,} tokens)
   
   RESULT:
   {'-'*60}
{result_str[:2000]}{'... [TRUNCATED]' if len(result_str) > 2000 else ''}
   {'-'*60}
"""
    _write_log(entry)
    print(f"📝 TOKEN_LOG: Tool result {tool_name} - {char_count:,} chars (~{token_estimate:,} tokens)")

def log_token_usage(prompt_tokens: int, completion_tokens: int, total_tokens: int):
    """Log actual token usage from the API"""
    entry = f"""
📊 TOKEN USAGE (from API)
   Prompt Tokens: {prompt_tokens:,}
   Completion Tokens: {completion_tokens:,}
   Total Tokens: {total_tokens:,}
"""
    _write_log(entry)
    print(f"📝 TOKEN_LOG: API reported {prompt_tokens:,} prompt + {completion_tokens:,} completion = {total_tokens:,} total")

def log_final_response(response: str, thread_id: str = None):
    """Log the final response being sent back"""
    char_count = len(response) if response else 0
    token_estimate = _estimate_tokens(response)
    
    entry = f"""
✅ FINAL RESPONSE
   Thread ID: {thread_id or 'N/A'}
   Length: {char_count:,} chars (~{token_estimate:,} tokens)
   
   RESPONSE:
   {'-'*60}
{response[:2000]}{'... [TRUNCATED]' if len(response) > 2000 else ''}
   {'-'*60}
"""
    _write_log(entry)
    log_separator("END OF REQUEST")
    print(f"📝 TOKEN_LOG: Final response - {char_count:,} chars (~{token_estimate:,} tokens)")


def log_all_run_steps(run_steps, thread_id: str, run_id: str):
    """
    Log ALL run steps with FULL content to see exactly what Azure is accumulating.
    This is the key to understanding the token inflation.
    """
    entry = f"""
{'#'*80}
  🔍 FULL RUN STEPS BREAKDOWN - Thread: {thread_id}, Run: {run_id}
  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'#'*80}
"""
    _write_log(entry)
    
    total_accumulated_tokens = 0
    step_count = 0
    
    # Handle different formats of run_steps
    steps_list = []
    if hasattr(run_steps, 'data'):
        steps_list = run_steps.data
    elif hasattr(run_steps, '__iter__'):
        steps_list = list(run_steps)
    
    for step in steps_list:
        step_count += 1
        step_id = getattr(step, 'id', 'N/A')
        step_type = getattr(step, 'type', 'N/A')
        step_status = getattr(step, 'status', 'N/A')
        
        entry = f"""
{'='*60}
STEP #{step_count} - Type: {step_type}, Status: {step_status}
ID: {step_id}
{'='*60}
"""
        _write_log(entry)
        
        # Check for step_details
        if hasattr(step, 'step_details'):
            details = step.step_details
            details_type = getattr(details, 'type', 'unknown')
            
            entry = f"   Details Type: {details_type}\n"
            _write_log(entry)
            
            # TOOL CALLS
            if details_type == 'tool_calls' and hasattr(details, 'tool_calls'):
                for tc_idx, tool_call in enumerate(details.tool_calls):
                    tc_type = getattr(tool_call, 'type', 'unknown')
                    tc_id = getattr(tool_call, 'id', 'N/A')
                    
                    entry = f"""
   TOOL CALL #{tc_idx + 1} (Type: {tc_type}, ID: {tc_id})
   {'-'*50}
"""
                    _write_log(entry)
                    
                    # MCP Tool Call
                    if hasattr(tool_call, 'mcp') and tool_call.mcp:
                        mcp = tool_call.mcp
                        mcp_name = getattr(mcp, 'name', 'unknown')
                        mcp_server = getattr(mcp, 'server_label', 'unknown')
                        mcp_args = getattr(mcp, 'arguments', {})
                        mcp_output = getattr(mcp, 'output', '')
                        
                        args_str = json.dumps(mcp_args, indent=2) if isinstance(mcp_args, dict) else str(mcp_args)
                        output_str = str(mcp_output) if mcp_output else '(no output yet)'
                        
                        args_tokens = _estimate_tokens(args_str)
                        output_tokens = _estimate_tokens(output_str)
                        total_accumulated_tokens += args_tokens + output_tokens
                        
                        entry = f"""   MCP TOOL: {mcp_name} (server: {mcp_server})
   
   ARGUMENTS ({len(args_str):,} chars, ~{args_tokens:,} tokens):
{args_str}

   OUTPUT ({len(output_str):,} chars, ~{output_tokens:,} tokens):
{output_str}
"""
                        _write_log(entry)
                    
                    # Function Tool Call  
                    elif hasattr(tool_call, 'function') and tool_call.function:
                        func = tool_call.function
                        func_name = getattr(func, 'name', 'unknown')
                        func_args = getattr(func, 'arguments', '{}')
                        func_output = getattr(func, 'output', '')
                        
                        args_str = str(func_args)
                        output_str = str(func_output) if func_output else '(no output yet)'
                        
                        args_tokens = _estimate_tokens(args_str)
                        output_tokens = _estimate_tokens(output_str)
                        total_accumulated_tokens += args_tokens + output_tokens
                        
                        entry = f"""   FUNCTION: {func_name}
   
   ARGUMENTS ({len(args_str):,} chars, ~{args_tokens:,} tokens):
{args_str}

   OUTPUT ({len(output_str):,} chars, ~{output_tokens:,} tokens):
{output_str}
"""
                        _write_log(entry)
                    
                    else:
                        # Unknown tool type - dump everything
                        entry = f"   UNKNOWN TOOL TYPE - Full object: {tool_call}\n"
                        entry += f"   Attributes: {dir(tool_call)}\n"
                        _write_log(entry)
            
            # MESSAGE CREATION
            elif details_type == 'message_creation' and hasattr(details, 'message_creation'):
                msg_creation = details.message_creation
                msg_id = getattr(msg_creation, 'message_id', 'N/A')
                entry = f"   MESSAGE CREATION: {msg_id}\n"
                _write_log(entry)
    
    # Summary
    entry = f"""
{'#'*80}
  📊 RUN STEPS SUMMARY
  Total Steps: {step_count}
  Estimated Accumulated Content: ~{total_accumulated_tokens:,} tokens
{'#'*80}
"""
    _write_log(entry)
    print(f"📝 TOKEN_LOG: Logged {step_count} run steps (~{total_accumulated_tokens:,} tokens accumulated)")

# Initialize log file
log_separator("QUICKBOOKS AGENT TOKEN LOGGER INITIALIZED")
print(f"📝 TOKEN_LOG: Logging to {LOG_FILE}")
