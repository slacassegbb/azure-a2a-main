import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Union
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from fastmcp import FastMCP
from fastmcp.tools import FunctionTool
from fastmcp.exceptions import ResourceError, ToolError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ServiceNowAuth:
    """ServiceNow authentication handler"""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

class ServiceNowClient:
    """ServiceNow client for making API calls"""
    
    def __init__(self):
        self.instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        self.username = os.getenv("SERVICENOW_USERNAME")
        self.password = os.getenv("SERVICENOW_PASSWORD")
        self.instance = os.getenv("SERVICENOW_INSTANCE")
        
        if not all([self.instance_url, self.username, self.password, self.instance]):
            raise ValueError("Missing required ServiceNow environment variables")
        
        # Initialize session as None - will be created lazily
        self.session = None
    
    async def _get_session(self):
        """Lazily create and return aiohttp session"""
        if self.session is None:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=60)  # bump timeout for slower instances
            self.session = aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.username, self.password),
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )
        return self.session
    
    async def search_records(self, table: str = "incident", query: str = "", limit: int = 10) -> Dict[str, Any]:
        """Search for records in ServiceNow.
        Supports both encoded queries and keyword (full-text) search.
        If query is a plain phrase (no encoded markers), uses 123TEXTQUERY321.
        If query is empty or a generic phrase like 'all incidents', fetches latest records.
        """
        try:
            # Normalize generic phrases and clean keyword quotes
            raw_query = (query or "")
            effective_query = raw_query
            normalized = raw_query.strip().lower()
            # Clean smart quotes and surrounding quotes for keyword searching
            import re as _re
            kw = raw_query
            kw = kw.replace("\u2018", "'").replace("\u2019", "'")  # ‘ ’ → '
            kw = kw.replace("\u201C", '"').replace("\u201D", '"')  # “ ” → "
            kw = kw.strip().strip("'").strip('"').strip()
            is_encoded = False
            generic_intent = (
                not normalized
                or normalized in {"all", "all incidents", "incidents", "recent incidents", "open incidents"}
                or ("incident" in normalized and any(kw in normalized for kw in ["all", "list", "show", "find"]))
            )
            if generic_intent:
                # No sysparm_query → return most recent records within limit
                url = f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}"
            else:
                # Decide encoded vs natural language; prefer encoded multi-field search for NL queries
                markers = ["=", "^", "like", "startswith", "endswith", ".", ">", "<"]
                is_encoded = any(m in normalized for m in markers)
                if is_encoded:
                    import urllib.parse
                    import re

                    def _normalize_like(match: re.Match) -> str:
                        field = match.group(1)
                        value = match.group(2)

                        cleaned = value.strip()
                        if cleaned.startswith(('"', "'")) and cleaned.endswith(('"', "'")):
                            cleaned = cleaned[1:-1]

                        decoded = urllib.parse.unquote(cleaned)
                        needs_encoding = cleaned == decoded and any(ch in decoded for ch in [' ', '\t'])
                        encoded = urllib.parse.quote(decoded) if needs_encoding else decoded
                        return f"{field}LIKE{encoded}"

                    like_pattern = re.compile(r"(\w+(?:\.\w+)?)LIKE([^\^]+)")
                    fixed_query = like_pattern.sub(_normalize_like, query)

                    if fixed_query != query:
                        print(f"🔍 Original query: {raw_query}")
                        print(f"🔍 Normalized query: {fixed_query}")
                    effective_query = fixed_query
                    url = f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}&sysparm_query={fixed_query}"
                else:
                    # Natural language keyword → encoded multi-field OR (deterministic)
                    import urllib.parse
                    encoded_kw = urllib.parse.quote(kw)
                    if table == "incident":
                        enc = (
                            f"short_descriptionLIKE{encoded_kw}^ORdescriptionLIKE{encoded_kw}^"
                            f"ORcaller_id.nameLIKE{encoded_kw}^ORopened_by.nameLIKE{encoded_kw}^ORassigned_to.nameLIKE{encoded_kw}"
                        )
                    elif table == "sys_user":
                        enc = f"nameLIKE{encoded_kw}^ORuser_nameLIKE{encoded_kw}^ORemailLIKE{encoded_kw}"
                    else:
                        enc = f"short_descriptionLIKE{encoded_kw}^ORdescriptionLIKE{encoded_kw}"
                    effective_query = enc
                    url = f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}&sysparm_query={enc}"
            print(f"🔍 ServiceNow API call: {url}")
            
            # Create a new session for this request to avoid timeout context issues
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.username, self.password),
                headers={"Content-Type": "application/json"},
                timeout=timeout
            ) as session:
                async with session.get(url) as response:
                    print(f"🔍 ServiceNow response status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        records = data.get("result", [])
                        result = {
                            "success": True,
                            "count": len(records),
                            "records": records,
                            "table": table,
                            "query": effective_query
                        }
                        fallback_applied = False
                        # Fallback 1: if no results and it was a keyword search, try encoded fields
                        if (not records) and (not is_encoded) and normalized and not fallback_applied:
                            enc = (
                                f"short_descriptionLIKE{kw}^ORdescriptionLIKE{kw}^"
                                f"ORcaller_id.nameLIKE{kw}^ORopened_by.nameLIKE{kw}^ORassigned_to.nameLIKE{kw}"
                            )
                            enc_url = f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}&sysparm_query={enc}"
                            print(f"🔍 Fallback API call (encoded fields): {enc_url}")
                            async with session.get(enc_url) as enc_resp:
                                print(f"🔍 Fallback (encoded) status: {enc_resp.status}")
                                if enc_resp.status == 200:
                                    enc_data = await enc_resp.json()
                                    enc_records = enc_data.get("result", [])
                                    if enc_records:
                                        result = {
                                            "success": True,
                                            "count": len(enc_records),
                                            "records": enc_records,
                                            "table": table,
                                            "query": enc
                                        }
                                        fallback_applied = True
                        # Fallback 2: still none → plain recent fetch
                        if (not result.get("records")) and (not normalized or not is_encoded) and not fallback_applied:
                            fallback_url = f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}"
                            print(f"🔍 Fallback API call (no query): {fallback_url}")
                            async with session.get(fallback_url) as fb_resp:
                                print(f"🔍 Fallback response status: {fb_resp.status}")
                                if fb_resp.status == 200:
                                    fb_data = await fb_resp.json()
                                    fb_records = fb_data.get("result", [])
                                    result = {
                                        "success": True,
                                        "count": len(fb_records),
                                        "records": fb_records,
                                        "table": table,
                                        "query": query or "(fallback)"
                                    }
                        if (not records) and is_encoded and "^" in effective_query:
                            segments = [seg for seg in effective_query.split("^") if seg]
                            filter_terms = ("urgency", "priority")
                            filtered_segments = [
                                seg for seg in segments
                                if not any(term in seg.lower() for term in filter_terms)
                            ]
                            if filtered_segments and len(filtered_segments) != len(segments):
                                reduced_query = "^".join(filtered_segments)
                                reduced_url = f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}&sysparm_query={reduced_query}"
                                print(f"🔍 Fallback API call (reduced filters): {reduced_url}")
                                async with session.get(reduced_url) as reduced_resp:
                                    print(f"🔍 Fallback (reduced) status: {reduced_resp.status}")
                                    if reduced_resp.status == 200:
                                        reduced_data = await reduced_resp.json()
                                        reduced_records = reduced_data.get("result", [])
                                        if reduced_records:
                                            result = {
                                                "success": True,
                                                "count": len(reduced_records),
                                                "records": reduced_records,
                                                "table": table,
                                                "query": reduced_query
                                            }
                                            fallback_applied = True
                            if not fallback_applied:
                                caller_like_segments = [seg for seg in segments if "caller_idlike" in seg.lower()]
                                if caller_like_segments:
                                    import urllib.parse
                                    target_value = caller_like_segments[0].split("LIKE", 1)[1].strip().strip('"').strip("'")
                                    if target_value:
                                        decoded_value = urllib.parse.unquote(target_value)
                                        encoded_value = urllib.parse.quote(decoded_value)
                                        caller_fallback_query = (
                                            f"short_descriptionLIKE{encoded_value}^ORdescriptionLIKE{encoded_value}^"
                                            f"ORcaller_id.nameLIKE{encoded_value}^ORopened_by.nameLIKE{encoded_value}^ORassigned_to.nameLIKE{encoded_value}"
                                        )
                                        caller_fallback_url = (
                                            f"{self.instance_url}/api/now/table/{table}?sysparm_limit={limit}&sysparm_query={caller_fallback_query}"
                                        )
                                        print(f"🔍 Fallback API call (caller content search): {caller_fallback_url}")
                                        async with session.get(caller_fallback_url) as caller_resp:
                                            print(f"🔍 Fallback (caller search) status: {caller_resp.status}")
                                            if caller_resp.status == 200:
                                                caller_data = await caller_resp.json()
                                                caller_records = caller_data.get("result", [])
                                                if caller_records:
                                                    result = {
                                                        "success": True,
                                                        "count": len(caller_records),
                                                        "records": caller_records,
                                                        "table": table,
                                                        "query": caller_fallback_query
                                                    }
                                                    fallback_applied = True
                        print(f"🔍 ServiceNow search successful: {result}")
                        return result
                    else:
                        error_text = await response.text()
                        print(f"🔍 ServiceNow API error: HTTP {response.status}: {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}",
                            "table": table,
                            "query": query
                        }
        except Exception as e:
            print(f"🔍 ServiceNow search exception: {e}")
            import traceback
            print(f"🔍 Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "table": table,
                "query": query
            }
    
    async def create_incident(self, short_description: str, description: str = None, priority: int = 3) -> Dict[str, Any]:
        """Create a new incident in ServiceNow"""
        try:
            incident_data = {
                "short_description": short_description,
                "priority": priority
            }
            
            if description:
                incident_data["description"] = description
            
            url = f"{self.instance_url}/api/now/table/incident"
            
            # Create a new session for this request to avoid timeout context issues
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.username, self.password),
                headers={"Content-Type": "application/json"},
                timeout=timeout
            ) as session:
                async with session.post(url, json=incident_data) as response:
                    if response.status in [200, 201]:
                        data = await response.json()
                        return {
                            "success": True,
                            "incident_number": data.get("result", {}).get("number"),
                            "sys_id": data.get("result", {}).get("sys_id"),
                            "message": "Incident created successfully"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {await response.text()}",
                            "incident_data": incident_data
                        }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "incident_data": incident_data
            }
    
    async def close(self):
        """Close the HTTP client"""
        if self.session:
            await self.session.close()

class ServiceNowMCP:
    """ServiceNow MCP Server"""
    
    def __init__(self, 
                instance_url: str,
                auth: ServiceNowAuth,
                name: str = "ServiceNow MCP"):
        print("DEBUG: ServiceNowMCP initialization:")
        print(f"Received instance_url: {instance_url}")
        print(f"Received auth username: {auth.username}")
        # Print password loaded from env
        print(f"DEBUG: Password from auth object: {auth.password}")
        print(f"DEBUG: Password from os.environ before set: {os.getenv('SERVICENOW_PASSWORD')}")
        
        # Set environment variables for ServiceNowClient
        os.environ["SERVICENOW_USERNAME"] = auth.username
        os.environ["SERVICENOW_PASSWORD"] = auth.password
        os.environ["SERVICENOW_INSTANCE_URL"] = instance_url
        # Extract instance from URL instead of hardcoding
        if instance_url and "dev" in instance_url:
            import re
            instance_match = re.search(r'dev\d+', instance_url)
            if instance_match:
                os.environ["SERVICENOW_INSTANCE"] = instance_match.group()
            else:
                os.environ["SERVICENOW_INSTANCE"] = "dev355156"  # fallback to correct instance
        else:
            os.environ["SERVICENOW_INSTANCE"] = "dev355156"  # fallback to correct instance
        # Print password after set
        print(f"DEBUG: Password from os.environ after set: {os.getenv('SERVICENOW_PASSWORD')}")
        
        print("DEBUG: Set environment variables:")
        print(f"SERVICENOW_INSTANCE: {os.environ['SERVICENOW_INSTANCE']}")
        print(f"SERVICENOW_USERNAME: {os.environ['SERVICENOW_USERNAME']}")
        print(f"SERVICENOW_INSTANCE_URL: {os.environ['SERVICENOW_INSTANCE_URL']}")
        
        self.client = ServiceNowClient()
        self.mcp = FastMCP(
            name="ServiceNow MCP",
            version="2.0.0",
            instructions="MCP server for interacting with ServiceNow"
        )
        
        # HOOK INTO THE ACTUAL MCP SERVER REQUEST HANDLER
        original_mcp_server = self.mcp._mcp_server
        logger.info(f"🔧 MCP Server type: {type(original_mcp_server)}")
        logger.info(f"🔧 MCP Server attributes: {[attr for attr in dir(original_mcp_server) if not attr.startswith('_')]}")
        
        # Try to hook directly into the FastMCP's _mcp_list_tools method
        if hasattr(self.mcp, '_mcp_list_tools'):
            original_mcp_list_tools = self.mcp._mcp_list_tools
            
            async def debug_mcp_list_tools(request):
                logger.info(f"🔧 FASTMCP _mcp_list_tools CALLED:")
                logger.info(f"   Request type: {type(request)}")
                logger.info(f"   Request: {request}")
                try:
                    result = await original_mcp_list_tools(request)
                    logger.info(f"🔧 FASTMCP _mcp_list_tools SUCCESS:")
                    logger.info(f"   Result type: {type(result)}")
                    logger.info(f"   Result: {result}")
                    
                    # Log detailed tool information
                    if hasattr(result, 'tools') and result.tools:
                        logger.info(f"   Tools count: {len(result.tools)}")
                        for i, tool in enumerate(result.tools):
                            logger.info(f"   Tool {i+1}: {tool}")
                            if hasattr(tool, 'name'):
                                logger.info(f"     Name: {tool.name}")
                            if hasattr(tool, 'description'):
                                logger.info(f"     Description: {tool.description[:100]}...")
                    else:
                        logger.warning(f"   No tools in result or result.tools is empty")
                    
                    return result
                except Exception as e:
                    logger.error(f"🔧 FASTMCP _mcp_list_tools ERROR: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                    
            self.mcp._mcp_list_tools = debug_mcp_list_tools
            logger.info("✅ Successfully hooked FastMCP._mcp_list_tools")
        else:
            logger.debug("⚠️ _mcp_list_tools method not found on FastMCP (this is normal for some versions)")
            
        # Hook into the LowLevelServer.list_tools method - this is the final layer before response
        logger.info(f"🔧 Attempting to hook LowLevelServer.list_tools method...")
        
        if hasattr(original_mcp_server, 'list_tools'):
            original_list_tools = original_mcp_server.list_tools
            logger.info(f"🔧 Found list_tools on LowLevelServer: {original_list_tools}")
            
            async def debug_list_tools(request):
                logger.info(f"🔧 LowLevelServer.list_tools CALLED:")
                logger.info(f"   Request type: {type(request)}")
                logger.info(f"   Request: {request}")
                try:
                    result = await original_list_tools(request)
                    logger.info(f"🔧 LowLevelServer.list_tools SUCCESS:")
                    logger.info(f"   Result type: {type(result)}")
                    logger.info(f"   Result: {result}")
                    return result
                except Exception as e:
                    logger.error(f"🔧 LowLevelServer.list_tools ERROR: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                    
            original_mcp_server.list_tools = debug_list_tools
            logger.info("✅ Successfully hooked LowLevelServer.list_tools")
        else:
            logger.debug("⚠️ list_tools method not found on LowLevelServer (this is normal for some versions)")
        
        # Hook into the FastMCP's list_tools method - this is the main entry point
        if hasattr(self.mcp, 'list_tools'):
            original_fastmcp_list_tools = self.mcp.list_tools
            logger.info(f"🔧 Found list_tools on FastMCP: {original_fastmcp_list_tools}")
            
            async def debug_fastmcp_list_tools(request):
                logger.info(f"🔧 FASTMCP list_tools CALLED:")
                logger.info(f"   Args: {request}")
                logger.info(f"   Kwargs: {{}}")
                try:
                    result = await original_fastmcp_list_tools(request)
                    logger.info(f"🔧 FASTMCP list_tools SUCCESS:")
                    logger.info(f"   Result: {result}")
                    
                    # Convert FunctionTool objects to proper MCP ListToolsResponse format
                    if result and isinstance(result, list):
                        logger.info(f"   Converting {len(result)} FunctionTool objects to MCP format...")

                        # Let's try to import and use the actual MCP types
                        try:
                            from mcp.types import Tool, ListToolsResult
                            logger.info("   Successfully imported MCP types")

                            mcp_tools = []
                            for tool in result:
                                if hasattr(tool, 'name') and hasattr(tool, 'description'):
                                    # Get the tool parameters from the tool manager
                                    tool_def = None
                                    if hasattr(self.mcp, '_tool_manager') and hasattr(self.mcp._tool_manager, '_tools'):
                                        for name, tool_obj in self.mcp._tool_manager._tools.items():
                                            if name == tool.name:
                                                tool_def = tool_obj
                                                break

                                    # Create proper MCP Tool object with Azure-compliant schema
                                    if tool_def and hasattr(tool_def, 'parameters'):
                                        input_schema = tool_def.parameters.copy()

                                        # Azure AI Foundry requirements:
                                        # 1. additionalProperties must be false
                                        input_schema["additionalProperties"] = False

                                        # 2. All fields must be required, use consistent anyOf with null for optional
                                        if "properties" in input_schema:
                                            required_fields = []
                                            for field_name, field_def in input_schema["properties"].items():
                                                # If field has a default value, make it optional using anyOf with null
                                                if "default" in field_def:
                                                    original_type = field_def.get("type")
                                                    if original_type == "string":
                                                        field_def["anyOf"] = [{"type": "string"}, {"type": "null"}]
                                                        field_def.pop("type", None)
                                                    elif original_type == "integer":
                                                        field_def["anyOf"] = [{"type": "integer"}, {"type": "null"}]
                                                        field_def.pop("type", None)
                                                    # Remove default from schema as Azure doesn't support it
                                                    field_def.pop("default", None)

                                                # All fields are required in Azure (even optional ones with null)
                                                required_fields.append(field_name)

                                            input_schema["required"] = required_fields
                                    else:
                                        input_schema = {
                                            "type": "object",
                                            "properties": {},
                                            "required": [],
                                            "additionalProperties": False
                                        }

                                    mcp_tool = Tool(
                                        name=tool.name,
                                        description=tool.description,
                                        inputSchema=input_schema
                                    )

                                    mcp_tools.append(mcp_tool)
                                    logger.info(f"   Converted tool: {mcp_tool.name} with inputSchema type: {type(mcp_tool.inputSchema)}")
                                    logger.info(f"   Full inputSchema: {mcp_tool.inputSchema}")
                                    logger.info(f"   Full MCP Tool: {mcp_tool}")

                            logger.info(f"   Converted {len(mcp_tools)} tools to proper MCP Tool objects")

                            # Try returning in FastMCP's native format but with our custom schemas
                            logger.info(f"🧪 TESTING: Returning FastMCP native format with custom schemas")
                            logger.info(f"   Tools count: {len(mcp_tools)}")
                            logger.info("   Using FastMCP native format that might have been working before")
                            
                            # Convert back to FastMCP FunctionTool format but with our custom schemas
                            from fastmcp.tools import FunctionTool
                            fastmcp_tools = []
                            for mcp_tool in mcp_tools:
                                # Create FunctionTool with our custom schema
                                fastmcp_tool = FunctionTool(
                                    name=mcp_tool.name,
                                    description=mcp_tool.description,
                                    parameters=mcp_tool.inputSchema
                                )
                                fastmcp_tools.append(fastmcp_tool)
                            
                            logger.info(f"   Created {len(fastmcp_tools)} FastMCP FunctionTool objects with custom schemas")
                            return fastmcp_tools

                        except ImportError as e:
                            logger.error(f"   Failed to import MCP types: {e}")
                            logger.info("   Falling back to dictionary format...")

                            # Fallback to dictionary format
                            mcp_tools = []
                            for tool in result:
                                if hasattr(tool, 'name') and hasattr(tool, 'description'):
                                    # Create a simple dictionary representation
                                    tool_dict = {
                                        "name": tool.name,
                                        "description": tool.description,
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {},
                                            "required": [],
                                            "additionalProperties": False
                                        }
                                    }
                                    mcp_tools.append(tool_dict)
                            
                            logger.info(f"   Created {len(mcp_tools)} dictionary tools as fallback")
                            return mcp_tools
                    else:
                        logger.warning(f"   No tools in result or result is not a list")
                        return result
                        
                except Exception as e:
                    logger.error(f"🔧 FASTMCP list_tools ERROR: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                    
            self.mcp.list_tools = debug_fastmcp_list_tools
            logger.info("✅ Successfully hooked FastMCP.list_tools")
        else:
            logger.debug("⚠️ list_tools method not found on FastMCP (this is normal for some versions)")
        
        # 🔧 CRITICAL FIX: Hook into tool execution to handle CallToolRequest
        logger.info(f"🔧 Attempting to hook tool execution methods...")
        
        # Hook into the LowLevelServer.call_tool method - this handles actual tool execution
        if hasattr(original_mcp_server, 'call_tool'):
            original_call_tool = original_mcp_server.call_tool
            logger.info(f"🔧 Found call_tool on LowLevelServer: {original_call_tool}")
            
            async def debug_call_tool(request):
                logger.info(f"🔧 LowLevelServer.call_tool CALLED:")
                logger.info(f"   Request type: {type(request)}")
                logger.info(f"   Request: {request}")
                try:
                    result = await original_call_tool(request)
                    logger.info(f"🔧 LowLevelServer.call_tool SUCCESS:")
                    logger.info(f"   Result type: {type(result)}")
                    logger.info(f"   Result: {result}")
                    return result
                except Exception as e:
                    logger.error(f"🔧 LowLevelServer.call_tool ERROR: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                    
            original_mcp_server.call_tool = debug_call_tool
            logger.info("✅ Successfully hooked LowLevelServer.call_tool")
        else:
            logger.debug("⚠️ call_tool method not found on LowLevelServer (this is normal for some versions)")
        
        # Hook into the FastMCP's call_tool method if it exists
        if hasattr(self.mcp, 'call_tool'):
            original_fastmcp_call_tool = self.mcp.call_tool
            logger.info(f"🔧 Found call_tool on FastMCP: {original_fastmcp_call_tool}")
            
            async def debug_fastmcp_call_tool(request):
                logger.info(f"🔧 FASTMCP call_tool CALLED:")
                logger.info(f"   Request: {request}")
                try:
                    result = await original_fastmcp_call_tool(request)
                    logger.info(f"🔧 FASTMCP call_tool SUCCESS:")
                    logger.info(f"   Result: {result}")
                    return result
                except Exception as e:
                    logger.error(f"🔧 FASTMCP call_tool ERROR: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                    
            self.mcp.call_tool = debug_fastmcp_call_tool
            logger.info("✅ Successfully hooked FastMCP.call_tool")
        else:
            logger.debug("⚠️ call_tool method not found on FastMCP (this is normal for some versions)")
        
        # 🔧 CRITICAL FIX: Hook into the MCP server's request handler to catch all requests
        if hasattr(original_mcp_server, 'handle_request'):
            original_handle_request = original_mcp_server.handle_request
            logger.info(f"🔧 Found handle_request on LowLevelServer: {original_handle_request}")
            
            async def debug_handle_request(request):
                logger.info(f"🔧 LowLevelServer.handle_request CALLED:")
                logger.info(f"   Request type: {type(request)}")
                logger.info(f"   Request: {request}")
                try:
                    result = await original_handle_request(request)
                    logger.info(f"🔧 LowLevelServer.handle_request SUCCESS:")
                    logger.info(f"   Result: {result}")
                    return result
                except Exception as e:
                    logger.error(f"🔧 LowLevelServer.handle_request ERROR: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                    
            original_mcp_server.handle_request = debug_handle_request
            logger.info("✅ Successfully hooked LowLevelServer.handle_request")
        else:
            logger.debug("⚠️ handle_request method not found on LowLevelServer (this is normal for some versions)")
        
        # Register the tools
        self.register_tools()
    
    def register_tools(self):
        """Register ServiceNow tools with the MCP server"""
        logger.info("🔧 Registering ServiceNow tools...")
        
        # Search records tool
        async def search_records(query: str = None, table: str = "incident", limit: int = 10, ctx=None):
            """Search for records in ServiceNow.
            
            Args:
                query: The search query to filter records
                ctx: MCP context object (injected automatically)
                table: The ServiceNow table to search in (default: incident)
                limit: Maximum number of records to return (default: 10)
            
            Returns:
                Dict containing the search results and metadata
            """
            logger.info(f"🔍 SEARCH_RECORDS CALLED:")
            logger.info(f"   Query: {query}")
            logger.info(f"   Table: {table}")
            logger.info(f"   Limit: {limit}")
            logger.info(f"   Context: {ctx}")
            
            try:
                result = await self.client.search_records(table=table, query=query, limit=limit)
                logger.info(f"   ✅ Search successful: {result}")
                return result
            except Exception as e:
                logger.error(f"   ❌ Search failed: {e}")
                raise ToolError(f"Failed to search ServiceNow: {str(e)}")
        
        # Create incident tool
        async def create_incident(short_description: str, description: str = None, priority: int = 3, ctx=None):
            """Create a new incident in ServiceNow
            
            Args:
                short_description: Brief description of the incident
                description: Detailed description of the incident
                priority: Incident priority (1-5)
                ctx: Optional context object for progress reporting
            """
            logger.info(f"🔧 CREATE_INCIDENT CALLED:")
            logger.info(f"   Short Description: {short_description}")
            logger.info(f"   Description: {description}")
            logger.info(f"   Priority: {priority}")
            logger.info(f"   Context: {ctx}")
            
            try:
                result = await self.client.create_incident(
                    short_description=short_description,
                    description=description,
                    priority=priority
                )
                logger.info(f"   ✅ Incident creation successful: {result}")
                return result
            except Exception as e:
                logger.error(f"   ❌ Incident creation failed: {e}")
                raise ToolError(f"Failed to create ServiceNow incident: {str(e)}")

        async def sn_create_incident(short_description: str, description: str = None, priority: int = 3, ctx=None):
            """Alias wrapper so agents can call sn_create_incident (matches instruction wording)."""
            return await create_incident(
                short_description=short_description,
                description=description,
                priority=priority,
                ctx=ctx,
            )
        
        # Register tools with FastMCP (core)
        self.mcp.tool(search_records)
        self.mcp.tool(create_incident)
        self.mcp.tool(sn_create_incident)

        # Additional SN-friendly aliases and helpers so Azure agent can pick them
        async def sn_search_incidents(query: str = "", limit: int = 10, ctx=None):
            """Search incidents via encoded query or keyword.
            For plain keywords, search across short_description, description, and user fields.
            """
            # Treat star/empty/generic as list-latest (no filter)
            if not query or query.strip() in {"*", "all", "incidents", "all incidents", "recent incidents"}:
                return await search_records(query="", table="incident", limit=limit, ctx=ctx)

            if query and not any(m in query for m in ["=", "^", ".", "LIKE", "STARTSWITH", "ENDSWITH", ">", "<"]):
                # Include description fields AND user-related fields - with URL encoding
                import urllib.parse
                encoded_query = urllib.parse.quote(query)
                enc = (
                    f"short_descriptionLIKE{encoded_query}^ORdescriptionLIKE{encoded_query}^"
                    f"ORcaller_id.nameLIKE{encoded_query}^ORcaller_id.user_nameLIKE{encoded_query}^ORcaller_id.emailLIKE{encoded_query}^"
                    f"ORopened_by.nameLIKE{encoded_query}^ORopened_by.user_nameLIKE{encoded_query}^ORopened_by.emailLIKE{encoded_query}^"
                    f"ORassigned_to.nameLIKE{encoded_query}^ORassigned_to.user_nameLIKE{encoded_query}^ORassigned_to.emailLIKE{encoded_query}"
                )
                url = f"{self.client.instance_url}/api/now/table/incident?sysparm_limit={limit}&sysparm_query={enc}"
                return await search_records(query=enc, table="incident", limit=limit, ctx=ctx)
            return await search_records(query=query, table="incident", limit=limit, ctx=ctx)


        async def sn_search_user(query: str, limit: int = 10, ctx=None):
            """Search ServiceNow users by name/username/email (sys_user)."""
            if query and not any(m in query for m in ["=", "^", ".", "LIKE", "STARTSWITH", "ENDSWITH"]):
                import urllib.parse
                encoded_query = urllib.parse.quote(query)
                enc = f"nameLIKE{encoded_query}^ORuser_nameLIKE{encoded_query}^ORemailLIKE{encoded_query}"
                return await search_records(query=enc, table="sys_user", limit=limit, ctx=ctx)
            return await search_records(query=query, table="sys_user", limit=limit, ctx=ctx)

        async def sn_list_users(limit: int = 10, ctx=None):
            return await search_records(query="", table="sys_user", limit=limit, ctx=ctx)

        async def sn_get_incident(number: str, ctx=None):
            # Minimal wrap: encoded query by number
            return await search_records(query=f"number={number}", table="incident", limit=1, ctx=ctx)

        async def sn_get_user_incidents(username: str, limit: int = 25, ctx=None):
            """Resolve user sys_id(s) then fetch incidents for caller/opened_by/assigned_to."""
            print(f"🔍 sn_get_user_incidents called with username: {username}")
            
            # 1) Resolve users - URL encode the username to handle spaces
            import urllib.parse

            seen_variations = set()

            def _add_variation(term: str, variations: list) -> None:
                cleaned = (term or "").strip()
                if not cleaned:
                    return
                key = cleaned.lower()
                if key not in seen_variations:
                    seen_variations.add(key)
                    variations.append(cleaned)

            username_variations: list[str] = []  # type: ignore[var-annotated]
            _add_variation(username, username_variations)
            if any(sep in username for sep in [".", "_"]):
                _add_variation(username.replace(".", " ").replace("_", " "), username_variations)
                _add_variation(username.replace(".", "").replace("_", ""), username_variations)
            if " " in username:
                parts = username.split()
                _add_variation(" ".join(parts), username_variations)
                _add_variation(" ".join(p.capitalize() for p in parts), username_variations)
                _add_variation("".join(parts), username_variations)

            encoded_username = urllib.parse.quote(username_variations[0])
            user_enc = f"nameLIKE{encoded_username}^ORuser_nameLIKE{encoded_username}^ORemailLIKE{encoded_username}"
            print(f"🔍 User search query: {user_enc}")
            users = await search_records(query=user_enc, table="sys_user", limit=5, ctx=ctx)
            print(f"🔍 User search result: {users}")
            
            if isinstance(users, dict):
                user_records = users.get("records", [])
            else:
                try:
                    user_records = json.loads(users).get("records", [])
                except Exception:
                    user_records = []
            
            print(f"🔍 Parsed user records: {len(user_records)} users found")
            for i, u in enumerate(user_records):
                print(f"🔍 User {i+1}: name='{u.get('name')}', user_name='{u.get('user_name')}', email='{u.get('email')}', sys_id='{u.get('sys_id')}'")

            if not user_records:
                print("🔍 No users found, trying alternate user search variations")
                for alt in username_variations[1:]:
                    alt_encoded = urllib.parse.quote(alt)
                    alt_query = f"nameLIKE{alt_encoded}^ORuser_nameLIKE{alt_encoded}^ORemailLIKE{alt_encoded}"
                    print(f"🔍 Alternate user search query: {alt_query}")
                    alt_users = await search_records(query=alt_query, table="sys_user", limit=5, ctx=ctx)
                    print(f"🔍 Alternate user search result: {alt_users}")
                    if isinstance(alt_users, dict):
                        user_records = alt_users.get("records", [])
                    else:
                        try:
                            user_records = json.loads(alt_users).get("records", [])
                        except Exception:
                            user_records = []
                    if user_records:
                        print(f"🔍 Found users via alternate variation '{alt}'")
                        break

            if not user_records:
                print(f"🔍 No users found after variations, trying incident content search as fallback")
                fallback_result = {"success": True, "count": 0, "records": [], "table": "incident", "query": ""}
                for term in username_variations:
                    encoded_term = urllib.parse.quote(term)
                    content_query = f"short_descriptionLIKE{encoded_term}^ORdescriptionLIKE{encoded_term}"
                    print(f"🔍 Incident content search query: {content_query}")
                    fallback_result = await search_records(query=content_query, table="incident", limit=limit, ctx=ctx)
                    print(f"🔍 Incident content search result: {fallback_result}")
                    if isinstance(fallback_result, dict) and fallback_result.get("records"):
                        print(f"🔍 Found incidents via content search variation '{term}'")
                        return fallback_result
                return fallback_result

            # Try sys_id-based search first
            ors = []
            for u in user_records:
                sid = u.get("sys_id") or u.get("id")
                if sid:
                    ors.append(f"caller_id={sid}")
                    ors.append(f"opened_by={sid}")
                    ors.append(f"assigned_to={sid}")
            
            print(f"🔍 Sys_id-based query parts: {ors}")
            
            if ors:
                inc_q = "^OR".join(ors)
                print(f"🔍 Sys_id-based incident query: {inc_q}")
                result = await search_records(query=inc_q, table="incident", limit=limit, ctx=ctx)
                print(f"🔍 Sys_id-based search result: {result}")
                
                # Check if we got results
                if isinstance(result, dict) and result.get("records"):
                    print(f"🔍 Sys_id search successful, returning {len(result.get('records', []))} incidents")
                    return result
                else:
                    print(f"🔍 Sys_id search returned no results, trying dot-walk fallback")
            else:
                print(f"🔍 No sys_ids found, going straight to dot-walk fallback")

            # Fallback: robust dot-walk by name/username/email
            print(f"🔍 Starting dot-walk fallback search")
            dotwalk_queries = []
            for u in user_records:
                name = (u.get("name") or "").strip()
                uname = (u.get("user_name") or "").strip()
                email = (u.get("email") or "").strip()
                
                if name:
                    encoded_name = urllib.parse.quote(name)
                    dotwalk_queries.append(f"caller_id.nameLIKE{encoded_name}")
                    dotwalk_queries.append(f"opened_by.nameLIKE{encoded_name}")
                    dotwalk_queries.append(f"assigned_to.nameLIKE{encoded_name}")
                if uname:
                    encoded_uname = urllib.parse.quote(uname)
                    dotwalk_queries.append(f"caller_id.user_nameLIKE{encoded_uname}")
                    dotwalk_queries.append(f"opened_by.user_nameLIKE{encoded_uname}")
                    dotwalk_queries.append(f"assigned_to.user_nameLIKE{encoded_uname}")
                if email:
                    encoded_email = urllib.parse.quote(email)
                    dotwalk_queries.append(f"caller_id.emailLIKE{encoded_email}")
                    dotwalk_queries.append(f"opened_by.emailLIKE{encoded_email}")
                    dotwalk_queries.append(f"assigned_to.emailLIKE{encoded_email}")
            
            print(f"🔍 Dot-walk queries: {dotwalk_queries}")
            
            if dotwalk_queries:
                dot_q = "^OR".join(dotwalk_queries)
                print(f"🔍 Final dot-walk query: {dot_q}")
                fallback_result = await search_records(query=dot_q, table="incident", limit=limit, ctx=ctx)
                print(f"🔍 Dot-walk fallback result: {fallback_result}")
                return fallback_result
            else:
                print(f"🔍 No dot-walk queries possible, returning empty result")
                return {"success": True, "count": 0, "records": [], "table": "incident", "query": "(no dot-walk possible)"}

        # Register helpers
        self.mcp.tool(sn_search_incidents)
        self.mcp.tool(sn_search_user)
        self.mcp.tool(sn_list_users)
        self.mcp.tool(sn_get_incident)
        self.mcp.tool(sn_get_user_incidents)

        logger.info("✅ ServiceNow tools registered successfully (core + SN helpers)!")

        # Update incident tool (add work notes/comments and change state)
        async def sn_update_incident(number: str = None, sys_id: str = None, state: Union[int, str, None] = None, work_notes: Optional[str] = None, comment: Optional[str] = None, ctx=None):
            """Update an incident by number or sys_id: set state, add work notes and/or comments."""
            import aiohttp
            # Resolve sys_id from number if needed
            try:
                target_sys_id = sys_id
                if not target_sys_id and number:
                    rec = await sn_get_incident(number=number, ctx=ctx)
                    if isinstance(rec, dict):
                        records = rec.get("records", [])
                        if records:
                            target_sys_id = records[0].get("sys_id")
                if not target_sys_id:
                    raise ToolError("sn_update_incident requires either sys_id or a valid incident number")

                # Map textual state to numeric if needed
                state_map = {
                    "New": 1,
                    "In Progress": 2,
                    "On Hold": 3,
                    "Resolved": 6,
                    "Closed": 7
                }
                payload: Dict[str, Any] = {}
                if work_notes:
                    payload["work_notes"] = work_notes
                if comment:
                    payload["comments"] = comment
                if state is not None:
                    if isinstance(state, str):
                        payload["state"] = state_map.get(state, state)
                    else:
                        payload["state"] = state

                url = f"{self.client.instance_url}/api/now/table/incident/{target_sys_id}"
                timeout = aiohttp.ClientTimeout(total=60)
                async with aiohttp.ClientSession(
                    auth=aiohttp.BasicAuth(self.client.username, self.client.password),
                    headers={"Content-Type": "application/json"},
                    timeout=timeout
                ) as session:
                    async with session.patch(url, json=payload) as resp:
                        status = resp.status
                        data = await resp.json(content_type=None)
                        if status in [200]:
                            return {
                                "success": True,
                                "message": "Incident updated",
                                "sys_id": target_sys_id,
                                "request": payload,
                                "result": data.get("result", data)
                            }
                        return {
                            "success": False,
                            "error": f"HTTP {status}: {await resp.text()}",
                            "sys_id": target_sys_id,
                            "request": payload
                        }
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Register update tool
        self.mcp.tool(sn_update_incident)
    
    def run(self, host: str = "127.0.0.1", port: int = 8005, transport: str = "http", path: str = "/mcp/"):
        """Run the MCP server"""
        logger.info(f"🚀 Starting ServiceNow MCP server with {transport.upper()} transport")
        logger.info(f"Server will be available at: http://{host}:{port}{path}")
        
        if transport == "http":
            # 🔧 CRITICAL FIX: Force pure HTTP transport to avoid session management issues
            logger.info("🔧 FORCING PURE HTTP TRANSPORT - bypassing FastMCP's transport system")
            
            # Create a custom HTTP server that handles MCP requests directly
            from fastapi import FastAPI, Request
            from fastapi.responses import JSONResponse
            import json
            import asyncio
            
            app = FastAPI()
            
            # Store reference to our MCP server
            mcp_server = self
            
            # Use the path parameter from CLI arguments
            @app.post(path)
            @app.post(path.rstrip("/"))
            async def handle_mcp_request(request: Request):
                """Handle MCP requests directly"""
                try:
                    body = await request.body()
                    body_text = body.decode()
                    logger.info(f"🔧 MCP REQUEST RECEIVED:")
                    logger.info(f"   Body: {body_text}")
                    
                    # Parse the JSON-RPC request
                    try:
                        data = json.loads(body_text)
                        method = data.get("method")
                        params = data.get("params", {})
                        request_id = data.get("id")
                        
                        logger.info(f"   Method: {method}")
                        logger.info(f"   Params: {params}")
                        logger.info(f"   Request ID: {request_id}")
                        
                        if method == "initialize":
                            logger.info("🔧 INITIALIZE REQUEST - sending capabilities")
                            # Send MCP server capabilities
                            result = {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {
                                    "tools": {}
                                },
                                "serverInfo": {
                                    "name": "ServiceNow MCP Server",
                                    "version": "1.0.0"
                                }
                            }
                            return JSONResponse(content={
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": result
                            })
                            
                        elif method == "tools/list":
                            logger.info("🔧 TOOL LIST REQUEST - calling FastMCP")
                            # Call FastMCP's list_tools method directly
                            try:
                                # Get the tools from FastMCP's tool manager
                                if hasattr(mcp_server.mcp, '_tool_manager') and hasattr(mcp_server.mcp._tool_manager, '_tools'):
                                    tools = list(mcp_server.mcp._tool_manager._tools.values())
                                    logger.info(f"   Found {len(tools)} tools in tool manager")
                                    
                                    # Convert tools to MCP format
                                    mcp_tools = []
                                    for tool in tools:
                                        if hasattr(tool, 'name') and hasattr(tool, 'description'):
                                            # Get the tool parameters
                                            parameters = {}
                                            if hasattr(tool, 'parameters'):
                                                parameters = tool.parameters.copy()
                                                # Ensure Azure compliance
                                                parameters["additionalProperties"] = False
                                                if "properties" in parameters:
                                                    required_fields = []
                                                    for field_name, field_def in parameters["properties"].items():
                                                        # Make all fields required (Azure requirement)
                                                        required_fields.append(field_name)
                                                        # Remove default values
                                                        if "default" in field_def:
                                                            field_def.pop("default", None)
                                                    parameters["required"] = required_fields
                                            
                                            # Create MCP tool format
                                            mcp_tool = {
                                                "name": tool.name,
                                                "description": tool.description,
                                                "inputSchema": parameters
                                            }
                                            mcp_tools.append(mcp_tool)
                                            logger.info(f"   Added tool: {tool.name}")
                                    
                                    logger.info(f"   Returning {len(mcp_tools)} tools")
                                    return JSONResponse(content={
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "result": {
                                            "tools": mcp_tools
                                        }
                                    })
                                else:
                                    logger.error("   No tool manager found")
                                    return JSONResponse(content={
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "error": {
                                            "code": -32603,
                                            "message": "No tools available"
                                        }
                                    }, status_code=500)
                                    
                            except Exception as e:
                                logger.error(f"   Error getting tools: {e}")
                                import traceback
                                logger.error(f"   Traceback: {traceback.format_exc()}")
                                return JSONResponse(content={
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "error": {
                                        "code": -32603,
                                        "message": f"Failed to get tools: {str(e)}"
                                    }
                                }, status_code=500)
                            
                        elif method == "tools/call":
                            tool_name = params.get("name")
                            arguments = params.get("arguments", {})
                            logger.info(f"🔧 TOOL EXECUTION REQUEST:")
                            logger.info(f"   Tool: {tool_name}")
                            logger.info(f"   Arguments: {arguments}")
                            
                            # Execute the tool through FastMCP's tool manager
                            try:
                                if hasattr(mcp_server.mcp, '_tool_manager') and hasattr(mcp_server.mcp._tool_manager, '_tools'):
                                    if tool_name in mcp_server.mcp._tool_manager._tools:
                                        tool = mcp_server.mcp._tool_manager._tools[tool_name]
                                        logger.info(f"   Found tool: {tool}")
                                        
                                        # Execute the tool function with the arguments
                                        if hasattr(tool, 'fn'):
                                            logger.info(f"   Executing tool function: {tool.fn}")
                                            result = await tool.fn(**arguments)
                                            logger.info(f"   Tool execution result: {result}")
                                            
                                            # 🔧 CRITICAL FIX: Return Azure-compatible response format
                                            # Azure expects the result to be wrapped in a specific structure
                                            
                                            # First, let's log what we're actually returning
                                            logger.info(f"   Raw ServiceNow result: {result}")
                                            
                                            # 🔧 Return MCP-compliant tool result shape for Azure AI Foundry
                                            # Spec: result must be an object with `content`: ResultContent[], optional `isError` boolean
                                            # We'll include both a brief text summary (when possible) and the raw JSON payload

                                            summary_text = None
                                            try:
                                                if isinstance(result, dict):
                                                    if result.get("success") and isinstance(result.get("records"), list):
                                                        count = result.get("count", len(result.get("records", [])))
                                                        summary_text = f"Found {count} records in ServiceNow for tool {tool_name}."
                                                    elif "message" in result and isinstance(result["message"], str):
                                                        summary_text = result["message"]
                                            except Exception:
                                                # Best-effort summary; do not fail tool call on summary creation
                                                summary_text = None

                                            # Compose a single text content item (Azure may not accept custom JSON content types)
                                            import json as _json
                                            if isinstance(result, str):
                                                message_text = result
                                            else:
                                                pretty_json = _json.dumps(result, indent=2, ensure_ascii=False)
                                                if summary_text:
                                                    message_text = f"{summary_text}\n\nData:\n{pretty_json}"
                                                else:
                                                    message_text = f"Tool {tool_name} executed successfully.\n\nData:\n{pretty_json}"

                                            content_items = [{"type": "text", "text": message_text}]

                                            mcp_tool_result = {
                                                "content": content_items,
                                                "isError": False
                                            }

                                            logger.info("   Returning MCP-compliant result with content items: "
                                                        f"{[item.get('type') for item in content_items]}")

                                            return JSONResponse(content={
                                                "jsonrpc": "2.0",
                                                "id": request_id,
                                                "result": mcp_tool_result
                                            })
                                        else:
                                            logger.error(f"   Tool {tool_name} has no fn attribute")
                                            return JSONResponse(content={
                                                "jsonrpc": "2.0",
                                                "id": request_id,
                                                "error": {
                                                    "code": -32603,
                                                    "message": f"Tool {tool_name} has no fn attribute"
                                                }
                                            }, status_code=500)
                                    else:
                                        logger.error(f"   Tool {tool_name} not found in tool manager")
                                        return JSONResponse(content={
                                            "jsonrpc": "2.0",
                                            "id": request_id,
                                            "error": {
                                                "code": -32601,
                                                "message": f"Tool {tool_name} not found"
                                            }
                                        }, status_code=404)
                                else:
                                    logger.error("   Tool manager not accessible")
                                    return JSONResponse(content={
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "error": {
                                            "code": -32603,
                                            "message": "Tool manager not accessible"
                                        }
                                    }, status_code=500)
                            except Exception as e:
                                logger.error(f"   Error executing tool {tool_name}: {e}")
                                import traceback
                                logger.error(f"   Traceback: {traceback.format_exc()}")
                                return JSONResponse(content={
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "error": {
                                        "code": -32603,
                                        "message": f"Error executing tool: {str(e)}"
                                    }
                                }, status_code=500)
                                
                        elif method == "notifications/initialized":
                            logger.info("🔧 NOTIFICATIONS/INITIALIZED REQUEST - acknowledging")
                            # This is a notification, not a request, so we don't need to return a result
                            # Just acknowledge it with a success response
                            # Handle case where request_id might be None for notifications
                            if request_id is not None:
                                return JSONResponse(content={
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "result": None
                                })
                            else:
                                # For notifications without ID, just return success
                                return JSONResponse(content={
                                    "jsonrpc": "2.0",
                                    "result": None
                                })
                        else:
                            logger.warning(f"   Unknown method: {method}")
                            return JSONResponse(content={
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32601,
                                    "message": f"Method not found: {method}"
                                }
                            }, status_code=404)
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"   Invalid JSON: {e}")
                        return JSONResponse(content={
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": -32700,
                                "message": "Parse error"
                            }
                        }, status_code=400)
                        
                except Exception as e:
                    logger.error(f"   Error handling request: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    return JSONResponse(content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {str(e)}"
                        }
                    }, status_code=500)
            
            @app.get(path)
            @app.get(path.rstrip("/"))
            async def handle_mcp_get():
                """Handle GET requests to the configured path"""
                return JSONResponse(content={"status": "ServiceNow MCP Server is running"})
            
            logger.info("✅ Custom HTTP server created with direct MCP handling")
            
            # Start the custom server
            import uvicorn
            uvicorn.run(app, host=host, port=port)
        else:
            # Use FastMCP's run method
            self.mcp.run(host=host, port=port, transport=transport)
    
    async def close(self):
        """Close the MCP server and cleanup"""
        try:
            if hasattr(self, 'client'):
                await self.client.close()
            logger.info("✅ ServiceNow MCP server closed successfully")
        except Exception as e:
            logger.error(f"Server error: {str(e)}")
            raise
        finally:
            asyncio.run(self.close())

# Factory functions for creating authentication
def create_basic_auth(username: str, password: str) -> ServiceNowAuth:
    """Create ServiceNowAuth object for ServiceNow authentication"""
    return ServiceNowAuth(username, password)

def create_oauth_auth(client_id: str, client_secret: str, username: str, password: str) -> ServiceNowAuth:
    """Create ServiceNowAuth object for OAuth authentication"""
    # For now, just use basic auth
    # TODO: Implement OAuth flow
    return ServiceNowAuth(username, password)

if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def main():
        # Create auth (you'll need to set these environment variables)
        username = os.getenv("SERVICENOW_USERNAME", "admin")
        password = os.getenv("SERVICENOW_PASSWORD", "password")
        instance_url = os.getenv("SERVICENOW_INSTANCE_URL", "https://dev355156.service-now.com")
        
        if not all([username, password, instance_url]):
            print("❌ Missing required environment variables:")
            print("   SERVICENOW_USERNAME")
            print("   SERVICENOW_PASSWORD") 
            print("   SERVICENOW_INSTANCE_URL")
            return
        
        # Create and run the MCP server
        auth = create_basic_auth(username, password)
        server = ServiceNowMCP(instance_url, auth)
        
        try:
            server.run(transport="http")
        except KeyboardInterrupt:
            print("\n🛑 Server stopped by user")
        finally:
            asyncio.run(server.close())
    
    asyncio.run(main())
