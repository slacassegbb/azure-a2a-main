#!/usr/bin/env python3
"""
Script to apply parallel execution fixes to all remote agent executors.
This adds force_new parameter to _get_or_create_thread and removes forced sleep delays.
"""
import os
import re

REMOTE_AGENTS_DIR = "/Users/simonlacasse/Downloads/sl-a2a-main2/remote_agents"

# Skip these as they're already fixed
SKIP_AGENTS = ["azurefoundry_image_generator", "azurefoundry_image_analysis", "google_adk"]

def fix_get_or_create_thread(content: str) -> str:
    """Add force_new parameter to _get_or_create_thread method."""
    
    # Pattern to match the method signature without force_new
    old_pattern = r'''(async def _get_or_create_thread\(\s*
        self,\s*
        context_id: str,\s*
        agent: Optional\[[^\]]+\] = None\s*
    \) -> str:\s*
        if agent is None:\s*
            agent = await self\._get_or_create_agent\(\)\s*
        # Reuse thread if it exists for this context_id\s*
        if context_id in self\._active_threads:\s*
            return self\._active_threads\[context_id\]\s*
        # Otherwise, create a new thread and store it\s*
        thread = await agent\.create_thread\(\)\s*
        thread_id = thread\.id\s*
        self\._active_threads\[context_id\] = thread_id\s*
        return thread_id)'''
    
    # Simpler approach - find and replace the signature first
    sig_old = r'(async def _get_or_create_thread\(\s*self,\s*context_id: str,\s*agent: Optional\[[^\]]+\] = None\s*\) -> str:)'
    
    # Check if force_new already exists
    if 'force_new: bool = False' in content:
        print("    - force_new already added")
        return content
    
    # Find the signature and add force_new parameter
    match = re.search(sig_old, content)
    if match:
        old_sig = match.group(1)
        # Extract the agent type
        agent_type_match = re.search(r'agent: Optional\[([^\]]+)\]', old_sig)
        if agent_type_match:
            agent_type = agent_type_match.group(1)
            new_sig = f'''async def _get_or_create_thread(
        self,
        context_id: str,
        agent: Optional[{agent_type}] = None,
        force_new: bool = False
    ) -> str:'''
            content = content.replace(old_sig, new_sig)
            print("    - Added force_new parameter to signature")
    
    # Now add the force_new logic after "if agent is None:" block
    old_logic = '''if agent is None:
            agent = await self._get_or_create_agent()
        # Reuse thread if it exists for this context_id
        if context_id in self._active_threads:
            return self._active_threads[context_id]'''
    
    new_logic = '''if agent is None:
            agent = await self._get_or_create_agent()
        # Force new thread for parallel requests to avoid thread conflicts
        if force_new:
            thread = await agent.create_thread()
            thread_id = thread.id
            logger.info(f"Created new thread {thread_id} for parallel request (context: {context_id})")
            self._active_threads[context_id] = thread_id
            return thread_id
        # Reuse thread if it exists for this context_id
        if context_id in self._active_threads:
            return self._active_threads[context_id]'''
    
    if old_logic in content and 'Force new thread for parallel requests' not in content:
        content = content.replace(old_logic, new_logic)
        print("    - Added force_new logic block")
    
    return content


def update_thread_call_site(content: str) -> str:
    """Update the call to _get_or_create_thread to use force_new=True."""
    
    # Pattern: thread_id = await self._get_or_create_thread(context_id, agent)
    old_call = 'thread_id = await self._get_or_create_thread(context_id, agent)'
    new_call = '''# Use force_new=True to create separate threads for parallel requests
            thread_id = await self._get_or_create_thread(context_id, agent, force_new=True)'''
    
    if old_call in content and 'force_new=True' not in content:
        content = content.replace(old_call, new_call)
        print("    - Updated call site with force_new=True")
    
    return content


def remove_forced_sleeps(content: str) -> str:
    """Remove the forced sleep delays in execute method."""
    
    # Pattern to find and replace the rate limiting section
    old_rate_limit = '''# Check if we're approaching the API limit
            if FoundryTemplateAgentExecutor._api_call_count >= FoundryTemplateAgentExecutor._max_api_calls_per_minute:
                wait_time = 60 - (current_time - FoundryTemplateAgentExecutor._api_call_window_start)
                if wait_time > 0:
                    logger.warning(f"API rate limit protection: waiting {wait_time:.1f}s to reset window")
                    await asyncio.sleep(wait_time)
                    # Reset counters
                    FoundryTemplateAgentExecutor._api_call_count = 0
                    FoundryTemplateAgentExecutor._api_call_window_start = time.time()
            
            # Enforce minimum interval between requests - THIS IS THE KEY FIX
            time_since_last = current_time - FoundryTemplateAgentExecutor._last_request_time
            if time_since_last < FoundryTemplateAgentExecutor._min_request_interval:
                sleep_time = FoundryTemplateAgentExecutor._min_request_interval - time_since_last
                logger.warning(f"🚦 RATE LIMITING: Waiting {sleep_time:.2f}s between user requests (last request was {time_since_last:.2f}s ago)")
                await asyncio.sleep(sleep_time)
            
            FoundryTemplateAgentExecutor._last_request_time = time.time()'''
    
    new_rate_limit = '''# Log if approaching API limit (but don't block for parallel execution)
            if FoundryTemplateAgentExecutor._api_call_count >= FoundryTemplateAgentExecutor._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count ({FoundryTemplateAgentExecutor._api_call_count}) at limit, requests may be throttled by Azure")
            
            FoundryTemplateAgentExecutor._api_call_count += 1
            FoundryTemplateAgentExecutor._last_request_time = time.time()'''
    
    # This is generic - we need to find the class name dynamically
    # Look for patterns with any executor class name
    pattern = r'''# Check if we're approaching the API limit\s+
            if \w+\._api_call_count >= \w+\._max_api_calls_per_minute:\s+
                wait_time = 60 - \(current_time - \w+\._api_call_window_start\)\s+
                if wait_time > 0:\s+
                    logger\.warning\(f"API rate limit protection: waiting \{wait_time:\.1f\}s to reset window"\)\s+
                    await asyncio\.sleep\(wait_time\)\s+
                    # Reset counters\s+
                    \w+\._api_call_count = 0\s+
                    \w+\._api_call_window_start = time\.time\(\)\s+
            \s+
            # Enforce minimum interval between requests.*?\s+
            time_since_last = current_time - \w+\._last_request_time\s+
            if time_since_last < \w+\._min_request_interval:\s+
                sleep_time = \w+\._min_request_interval - time_since_last\s+
                logger\.warning\(f"🚦 RATE LIMITING: Waiting \{sleep_time:\.2f\}s between user requests \(last request was \{time_since_last:\.2f\}s ago\)"\)\s+
                await asyncio\.sleep\(sleep_time\)\s+
            \s+
            \w+\._last_request_time = time\.time\(\)'''
    
    # Simpler approach - look for the unique markers
    if 'Enforce minimum interval between requests' in content and 'await asyncio.sleep(sleep_time)' in content:
        # Extract the executor class name
        class_match = re.search(r'class (\w+Executor)\(', content)
        if class_match:
            class_name = class_match.group(1)
            
            # Replace the old pattern with new one
            old_section = f'''# Check if we're approaching the API limit
            if {class_name}._api_call_count >= {class_name}._max_api_calls_per_minute:
                wait_time = 60 - (current_time - {class_name}._api_call_window_start)
                if wait_time > 0:
                    logger.warning(f"API rate limit protection: waiting {{wait_time:.1f}}s to reset window")
                    await asyncio.sleep(wait_time)
                    # Reset counters
                    {class_name}._api_call_count = 0
                    {class_name}._api_call_window_start = time.time()
            
            # Enforce minimum interval between requests - THIS IS THE KEY FIX
            time_since_last = current_time - {class_name}._last_request_time
            if time_since_last < {class_name}._min_request_interval:
                sleep_time = {class_name}._min_request_interval - time_since_last
                logger.warning(f"🚦 RATE LIMITING: Waiting {{sleep_time:.2f}}s between user requests (last request was {{time_since_last:.2f}}s ago)")
                await asyncio.sleep(sleep_time)
            
            {class_name}._last_request_time = time.time()'''
            
            new_section = f'''# Log if approaching API limit (but don't block for parallel execution)
            if {class_name}._api_call_count >= {class_name}._max_api_calls_per_minute:
                logger.warning(f"⚠️ API call count ({{{class_name}._api_call_count}}) at limit, requests may be throttled by Azure")
            
            {class_name}._api_call_count += 1
            {class_name}._last_request_time = time.time()'''
            
            if old_section in content:
                content = content.replace(old_section, new_section)
                print(f"    - Removed forced sleeps for {class_name}")
    
    return content


def process_file(filepath: str) -> bool:
    """Process a single executor file."""
    print(f"Processing: {filepath}")
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        original = content
        
        # Apply fixes
        content = fix_get_or_create_thread(content)
        content = update_thread_call_site(content)
        content = remove_forced_sleeps(content)
        
        if content != original:
            with open(filepath, 'w') as f:
                f.write(content)
            print(f"  ✅ Updated")
            return True
        else:
            print(f"  ⏭️ No changes needed")
            return False
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def main():
    """Process all remote agent executor files."""
    print("=" * 60)
    print("Applying parallel execution fixes to remote agents")
    print("=" * 60)
    
    updated = 0
    skipped = 0
    
    for agent_dir in os.listdir(REMOTE_AGENTS_DIR):
        if agent_dir in SKIP_AGENTS:
            print(f"Skipping {agent_dir} (already fixed)")
            skipped += 1
            continue
            
        executor_path = os.path.join(REMOTE_AGENTS_DIR, agent_dir, "foundry_agent_executor.py")
        if os.path.exists(executor_path):
            if process_file(executor_path):
                updated += 1
    
    print("=" * 60)
    print(f"Summary: {updated} files updated, {skipped} skipped")
    print("=" * 60)


if __name__ == "__main__":
    main()
