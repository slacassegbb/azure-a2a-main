"""
ServiceNow MCP Server

This module provides a Model Context Protocol (MCP) server that interfaces with ServiceNow.
It allows AI agents to access and manipulate ServiceNow data through a secure API.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Literal

import requests
import httpx
from pydantic import BaseModel, Field, field_validator

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

# ServiceNow API models
class IncidentState(int, Enum):
    NEW = 1
    IN_PROGRESS = 2 
    ON_HOLD = 3
    RESOLVED = 6
    CLOSED = 7
    CANCELED = 8

class IncidentPriority(int, Enum):
    CRITICAL = 1
    HIGH = 2
    MODERATE = 3
    LOW = 4
    PLANNING = 5

class IncidentUrgency(int, Enum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3

class IncidentImpact(int, Enum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3

class IncidentCreate(BaseModel):
    """Model for creating a new incident"""
    short_description: str = Field(..., description="A brief description of the incident")
    description: str = Field(..., description="A detailed description of the incident")
    caller_id: Optional[str] = Field(None, description="The sys_id or name of the caller")
    category: Optional[str] = Field(None, description="The incident category")
    subcategory: Optional[str] = Field(None, description="The incident subcategory")
    urgency: Optional[IncidentUrgency] = Field(IncidentUrgency.MEDIUM, description="The urgency of the incident")
    impact: Optional[IncidentImpact] = Field(IncidentImpact.MEDIUM, description="The impact of the incident")
    assignment_group: Optional[str] = Field(None, description="The sys_id or name of the assignment group")
    assigned_to: Optional[str] = Field(None, description="The sys_id or name of the assignee")

class IncidentUpdate(BaseModel):
    """Model for updating an existing incident"""
    short_description: Optional[str] = Field(None, description="A brief description of the incident")
    description: Optional[str] = Field(None, description="A detailed description of the incident")
    caller_id: Optional[str] = Field(None, description="The sys_id or name of the caller")
    category: Optional[str] = Field(None, description="The incident category")
    subcategory: Optional[str] = Field(None, description="The incident subcategory")
    urgency: Optional[IncidentUrgency] = Field(None, description="The urgency of the incident")
    impact: Optional[IncidentImpact] = Field(None, description="The impact of the incident")
    state: Optional[IncidentState] = Field(None, description="The state of the incident")
    assignment_group: Optional[str] = Field(None, description="The sys_id or name of the assignment group")
    assigned_to: Optional[str] = Field(None, description="The sys_id or name of the assignee")
    work_notes: Optional[str] = Field(None, description="Work notes to add to the incident (internal)")
    comments: Optional[str] = Field(None, description="Customer visible comments to add to the incident")
    
    @field_validator('work_notes', 'comments')
    @classmethod
    def validate_not_empty(cls, v):
        if v is not None and v.strip() == '':
            raise ValueError("Cannot be an empty string")
        return v

    class Config:
        use_enum_values = True
        
class QueryOptions(BaseModel):
    """Options for querying ServiceNow records"""
    limit: int = Field(10, description="Maximum number of records to return", ge=1, le=1000)
    offset: int = Field(0, description="Number of records to skip", ge=0)
    fields: Optional[List[str]] = Field(None, description="List of fields to return")
    query: Optional[str] = Field(None, description="ServiceNow encoded query string")
    order_by: Optional[str] = Field(None, description="Field to order results by")
    order_direction: Optional[Literal["asc", "desc"]] = Field("desc", description="Order direction")

class Authentication:
    """Base class for ServiceNow authentication methods"""
    
    async def get_headers(self) -> Dict[str, str]:
        """Get authentication headers for ServiceNow API requests"""
        raise NotImplementedError("Subclasses must implement this method")

class BasicAuth(Authentication):
    """Basic authentication for ServiceNow"""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        
    async def get_headers(self) -> Dict[str, str]:
        """Get authentication headers for ServiceNow API requests"""
        return {}
    
    def get_auth(self) -> tuple:
        """Get authentication tuple for requests"""
        return (self.username, self.password)

class TokenAuth(Authentication):
    """Token authentication for ServiceNow"""
    
    def __init__(self, token: str):
        self.token = token
        
    async def get_headers(self) -> Dict[str, str]:
        """Get authentication headers for ServiceNow API requests"""
        return {"Authorization": f"Bearer {self.token}"}
    
    def get_auth(self) -> None:
        """Get authentication tuple for requests"""
        return None

class OAuthAuth(Authentication):
    """OAuth authentication for ServiceNow"""
    
    def __init__(self, client_id: str, client_secret: str, username: str, password: str, 
                 instance_url: str, token: Optional[str] = None, refresh_token: Optional[str] = None,
                 token_expiry: Optional[datetime] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.instance_url = instance_url
        self.token = token
        self.refresh_token = refresh_token
        self.token_expiry = token_expiry
        
    async def get_headers(self) -> Dict[str, str]:
        """Get authentication headers for ServiceNow API requests"""
        if self.token is None or (self.token_expiry and datetime.now() > self.token_expiry):
            await self.refresh()
            
        return {"Authorization": f"Bearer {self.token}"}
    
    def get_auth(self) -> None:
        """Get authentication tuple for requests"""
        return None
        
    async def refresh(self):
        """Refresh the OAuth token"""
        if self.refresh_token:
            # Try refresh flow first
            data = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token
            }
        else:
            # Fall back to password flow
            data = {
                "grant_type": "password",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "username": self.username,
                "password": self.password
            }
            
        token_url = f"{self.instance_url}/oauth_token.do"
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            result = response.json()
            
            self.token = result["access_token"]
            self.refresh_token = result.get("refresh_token")
            expires_in = result.get("expires_in", 1800)  # Default 30 minutes
            self.token_expiry = datetime.now().timestamp() + expires_in

class ServiceNowClient:
    """Client for interacting with ServiceNow API"""
    
    def __init__(self, instance_url: str, auth: Authentication):
        self.instance_url = instance_url.rstrip('/')
        self.auth = auth
        self.client = httpx.AsyncClient()
        
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
        
    async def request(self, method: str, path: str, 
                    params: Optional[Dict[str, Any]] = None,
                    json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the ServiceNow API"""
        url = f"{self.instance_url}{path}"
        headers = await self.auth.get_headers()
        headers["Accept"] = "application/json"
        
        if isinstance(self.auth, BasicAuth):
            auth = self.auth.get_auth()
        else:
            auth = None
            
        try:
            response = await self.client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                auth=auth
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"ServiceNow API error: {e.response.text}")
            raise
            
    async def get_record(self, table: str, sys_id: str) -> Dict[str, Any]:
        """Get a record by sys_id"""
        return await self.request("GET", f"/api/now/table/{table}/{sys_id}")
        
    async def get_records(self, table: str, options: QueryOptions = None) -> Dict[str, Any]:
        """Get records with query options"""
        if options is None:
            options = QueryOptions()
            
        params = {
            "sysparm_limit": options.limit,
            "sysparm_offset": options.offset
        }
        
        if options.fields:
            params["sysparm_fields"] = ",".join(options.fields)
            
        if options.query:
            params["sysparm_query"] = options.query
            
        if options.order_by:
            direction = "desc" if options.order_direction == "desc" else "asc"
            params["sysparm_order_by"] = f"{options.order_by}^{direction}"
            
        return await self.request("GET", f"/api/now/table/{table}", params=params)
    
    async def create_record(self, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new record"""
        return await self.request("POST", f"/api/now/table/{table}", json_data=data)
        
    async def update_record(self, table: str, sys_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing record"""
        return await self.request("PUT", f"/api/now/table/{table}/{sys_id}", json_data=data)
        
    async def delete_record(self, table: str, sys_id: str) -> Dict[str, Any]:
        """Delete a record"""
        return await self.request("DELETE", f"/api/now/table/{table}/{sys_id}")
        
    async def get_incident_by_number(self, number: str) -> Dict[str, Any]:
        """Get an incident by its number"""
        result = await self.request("GET", f"/api/now/table/incident", 
                                  params={"sysparm_query": f"number={number}", "sysparm_limit": 1})
        if result.get("result") and len(result["result"]) > 0:
            return result["result"][0]
        return None
        
    async def search(self, query: str, table: str = "incident", limit: int = 10) -> Dict[str, Any]:
        """Search for records using text query"""
        return await self.request("GET", f"/api/now/table/{table}", 
                                params={"sysparm_query": f"123TEXTQUERY321={query}", "sysparm_limit": limit})
                                
    async def get_available_tables(self) -> List[str]:
        """Get a list of available tables"""
        result = await self.request("GET", "/api/now/table/sys_db_object", 
                                  params={"sysparm_fields": "name,label", "sysparm_limit": 100})
        return result.get("result", [])
        
    async def get_table_schema(self, table: str) -> Dict[str, Any]:
        """Get the schema for a table"""
        result = await self.request("GET", f"/api/now/ui/meta/{table}")
        return result


class ServiceNowMCP:
    """ServiceNow MCP Server"""
    
    def __init__(self, 
                instance_url: str,
                auth: Authentication,
                name: str = "ServiceNow MCP"):
        self.client = ServiceNowClient(instance_url, auth)
        self.mcp = FastMCP(name, dependencies=[
            "requests",
            "httpx", 
            "pydantic"
        ])

        # Helper: normalize common incident user filters when caller/opened_by/assigned_to are used
        # without dot-walking. Converts e.g. caller_id=david.miller →
        # caller_id.nameLIKEDavid Miller^ORcaller_id.user_name=david.miller
        import re
        def _normalize_incident_query(query: str) -> str:
            try:
                if not query:
                    return query
                parts = query.split('^')
                normalized_parts = []
                for part in parts:
                    m = re.match(r"\s*(caller_id|opened_by|assigned_to)=([^\^]+)\s*", part, flags=re.IGNORECASE)
                    if m and '.' not in part:
                        field = m.group(1)
                        value = m.group(2)
                        # Build robust OR across display name, username, and email with common variations
                        variations = set(
                            [value, value.lower(), value.upper(), value.title(),
                             value.replace('.', ' '), value.replace('_', ' '), value.replace(' ', '.'),
                             value.replace('.', ''), value.replace(' ', '')]
                        )
                        ors = []
                        for v in variations:
                            ors.append(f"{field}.nameLIKE{v}")
                            ors.append(f"{field}.user_nameLIKE{v}")
                            ors.append(f"{field}.emailLIKE{v}")
                        normalized_parts.append('^OR'.join(ors))
                    else:
                        normalized_parts.append(part)
                # If we introduced ORs, join them back with ^, allowing existing OR chains
                return '^'.join(normalized_parts)
            except Exception:
                return query
        self._normalize_incident_query = _normalize_incident_query
        
        # Register resources
        self.mcp.resource("servicenow://incidents")(self.list_incidents)
        self.mcp.resource("servicenow://incidents/{number}")(self.get_incident)
        self.mcp.resource("servicenow://users")(self.list_users)
        self.mcp.resource("servicenow://knowledge")(self.list_knowledge)
        self.mcp.resource("servicenow://tables")(self.get_tables)
        self.mcp.resource("servicenow://tables/{table}")(self.get_table_records)
        self.mcp.resource("servicenow://schema/{table}")(self.get_table_schema)
        
        # Register tools with debugging
        print("🔧 DEBUG: Registering MCP tools...")
        try:
            self.mcp.tool(name="create_incident")(self.create_incident)
            print("✅ Registered: create_incident")
        except Exception as e:
            print(f"❌ Failed to register create_incident: {e}")
            
        try:
            self.mcp.tool(name="update_incident")(self.update_incident)
            print("✅ Registered: update_incident")
        except Exception as e:
            print(f"❌ Failed to register update_incident: {e}")
            
        try:
            self.mcp.tool(name="search_records")(self.search_records)
            print("✅ Registered: search_records")
        except Exception as e:
            print(f"❌ Failed to register search_records: {e}")
            
        try:
            self.mcp.tool(name="get_record")(self.get_record)
            print("✅ Registered: get_record")
        except Exception as e:
            print(f"❌ Failed to register get_record: {e}")
            
        try:
            self.mcp.tool(name="perform_query")(self.perform_query)
            print("✅ Registered: perform_query")
        except Exception as e:
            print(f"❌ Failed to register perform_query: {e}")
            
        try:
            self.mcp.tool(name="add_comment")(self.add_comment)
            print("✅ Registered: add_comment")
        except Exception as e:
            print(f"❌ Failed to register add_comment: {e}")
            
        try:
            self.mcp.tool(name="add_work_notes")(self.add_work_notes)
            print("✅ Registered: add_work_notes")
        except Exception as e:
            print(f"❌ Failed to register add_work_notes: {e}")
            
        # Register ServiceNow alias tools expected by Azure Foundry agent
        try:
            self.mcp.tool(name="sn_create_incident")(self.create_incident)
            self.mcp.tool(name="sn_update_incident")(self.update_incident)
            self.mcp.tool(name="sn_add_comment")(self.add_comment)
            self.mcp.tool(name="sn_add_work_notes")(self.add_work_notes)
            print("✅ Registered SN aliases: create/update/add_comment/add_work_notes")
        except Exception as e:
            print(f"❌ Failed to register SN alias basics: {e}")

        # Wrapper tools to match Foundry agent expectations
        @self.mcp.tool(name="sn_get_incident")
        async def sn_get_incident(number: str, ctx: Context = None) -> str:
            """Get a specific incident by number (INC00..)."""
            return await self.get_incident(number)

        @self.mcp.tool(name="sn_search_incidents")
        async def sn_search_incidents(query: str = "", limit: int = 10, ctx: Context = None) -> str:
            """Search incidents via encoded query or keyword (uses perform_query if encoded)."""
            # If caller provided a plain name, escalate to normalized encoded query
            encoded_markers = ["=", "^", ".", "LIKE", "STARTSWITH", "ENDSWITH"]
            if not any(m in (query or "") for m in encoded_markers) and query:
                # Treat as name; search across caller/opened_by/assigned_to name/email/user_name
                enc = (
                    f"caller_id.nameLIKE{query}^ORcaller_id.user_nameLIKE{query}^ORcaller_id.emailLIKE{query}^"
                    f"ORopened_by.nameLIKE{query}^ORopened_by.user_nameLIKE{query}^ORopened_by.emailLIKE{query}^"
                    f"ORassigned_to.nameLIKE{query}^ORassigned_to.user_nameLIKE{query}^ORassigned_to.emailLIKE{query}"
                )
                return await self.perform_query(table="incident", query=enc, limit=limit, ctx=ctx)
            return await self.perform_query(table="incident", query=query, limit=limit, ctx=ctx)

        @self.mcp.tool(name="sn_search_user")
        async def sn_search_user(query: str, limit: int = 10, ctx: Context = None) -> str:
            """Search users by name/username/email (sys_user)."""
            return await self.perform_query(table="sys_user", query=query, limit=limit, ctx=ctx)

        @self.mcp.tool(name="sn_list_users")
        async def sn_list_users(limit: int = 10, ctx: Context = None) -> str:
            """List users from sys_user (limit configurable)."""
            return await self.perform_query(table="sys_user", limit=limit, ctx=ctx)

        @self.mcp.tool(name="sn_search_knowledge")
        async def sn_search_knowledge(query: str = "", limit: int = 10, ctx: Context = None) -> str:
            """Search knowledge articles (kb_knowledge)."""
            return await self.perform_query(table="kb_knowledge", query=query, limit=limit, ctx=ctx)

        @self.mcp.tool(name="sn_get_user_incidents")
        async def sn_get_user_incidents(username: str, limit: int = 10, ctx: Context = None) -> str:
            """Resolve user first, then fetch incidents by sys_id (caller/opened_by/assigned_to)."""
            try:
                if ctx:
                    await ctx.info(f"Resolving user: {username}")

                # 1) Find candidate users (display name, username, email)
                user_query = (
                    f"nameLIKE{username}^ORuser_nameLIKE{username}^ORemailLIKE{username}"
                )
                users_raw = await self.perform_query(table="sys_user", query=user_query, limit=5, ctx=ctx)
                users = json.loads(users_raw)
                candidates = users.get("result", []) if isinstance(users, dict) else []

                if ctx:
                    await ctx.info(f"Found {len(candidates)} user candidates")

                if not candidates:
                    return json.dumps({"result": [], "info": "No matching users"})

                # 2) Build incident encoded query by sys_id across common fields
                ors = []
                for u in candidates:
                    sys_id = u.get("sys_id") or u.get("id")
                    if not sys_id:
                        continue
                    ors.append(f"caller_id={sys_id}")
                    ors.append(f"opened_by={sys_id}")
                    ors.append(f"assigned_to={sys_id}")

                if not ors:
                    return json.dumps({"result": [], "info": "No usable sys_id for matched users"})

                # Join with ^OR
                inc_query = "^OR".join(ors)
                if ctx:
                    await ctx.info("Querying incidents for resolved user sys_id(s)")

                incidents = await self.perform_query(table="incident", query=inc_query, limit=limit, ctx=ctx)
                return incidents
            except Exception as e:
                if ctx:
                    await ctx.error(f"sn_get_user_incidents failed: {e}")
                return json.dumps({"error": str(e)})

        print(f"🔧 DEBUG: Total tools registered: {len(self.mcp._tools) if hasattr(self.mcp, '_tools') else 'Unknown'}")
        if hasattr(self.mcp, '_tools'):
            print(f"🔧 DEBUG: Tool names: {list(self.mcp._tools.keys())}")
        
        # Rely on FastMCP's default list_tools implementation (more compatible with Azure Agents)
        
        # Register prompts
        self.mcp.prompt(name="analyze_incident")(self.incident_analysis_prompt)
        self.mcp.prompt(name="create_incident_prompt")(self.create_incident_prompt)
    
    async def close(self):
        """Close the ServiceNow client"""
        await self.client.close()
        
    def run(self, transport: str = "stdio"):
        """Run the ServiceNow MCP server"""
        try:
            self.mcp.run(transport=transport)
        finally:
            asyncio.run(self.close())
        
    # Resource handlers
    async def list_incidents(self) -> str:
        """List recent incidents in ServiceNow"""
        options = QueryOptions(limit=10)
        result = await self.client.get_records("incident", options)
        return json.dumps(result, indent=2)
        
    async def get_incident(self, number: str) -> str:
        """Get a specific incident by number"""
        incident = await self.client.get_incident_by_number(number)
        if incident:
            return json.dumps({"result": incident}, indent=2)
        return json.dumps({"result": "Incident not found"})
        
    async def list_users(self) -> str:
        """List users in ServiceNow"""
        options = QueryOptions(limit=10)
        result = await self.client.get_records("sys_user", options)
        return json.dumps(result, indent=2)
        
    async def list_knowledge(self) -> str:
        """List knowledge articles in ServiceNow"""
        options = QueryOptions(limit=10)
        result = await self.client.get_records("kb_knowledge", options)
        return json.dumps(result, indent=2)
        
    async def get_tables(self) -> str:
        """Get a list of available tables"""
        result = await self.client.get_available_tables()
        return json.dumps({"result": result}, indent=2)
        
    async def get_table_records(self, table: str) -> str:
        """Get records from a specific table"""
        options = QueryOptions(limit=10)
        result = await self.client.get_records(table, options)
        return json.dumps(result, indent=2)
        
    async def get_table_schema(self, table: str) -> str:
        """Get the schema for a table"""
        result = await self.client.get_table_schema(table)
        return json.dumps(result, indent=2)
    
    # Tool handlers
    async def create_incident(self, 
                     incident: IncidentCreate,
                     ctx: Context = None) -> str:
        """
        Create a new incident in ServiceNow
        
        Args:
            incident: The incident details to create
            ctx: Optional context object for progress reporting
        
        Returns:
            JSON response from ServiceNow
        """
        if ctx:
            await ctx.info(f"Creating incident: {incident.short_description}")
            
        data = incident.dict(exclude_none=True)
        result = await self.client.create_record("incident", data)
        
        if ctx:
            # Handle different response structures
            try:
                if 'result' in result and isinstance(result['result'], dict):
                    # Standard ServiceNow response with nested result
                    incident_number = result['result'].get('number', 'Unknown')
                elif 'result' in result and isinstance(result['result'], list) and len(result['result']) > 0:
                    # Response with result as array
                    incident_number = result['result'][0].get('number', 'Unknown')
                elif 'number' in result:
                    # Direct response
                    incident_number = result.get('number', 'Unknown')
                else:
                    incident_number = 'Created successfully'
                
                await ctx.info(f"Created incident: {incident_number}")
            except Exception as e:
                await ctx.info(f"Created incident (number extraction failed): {str(e)}")
            
        return json.dumps(result, indent=2)
        
    async def update_incident(self,
                     number: str,
                     updates: IncidentUpdate,
                     ctx: Context = None) -> str:
        """
        Update an existing incident in ServiceNow
        
        Args:
            number: The incident number (INC0010001)
            updates: The fields to update
            ctx: Optional context object for progress reporting
            
        Returns:
            JSON response from ServiceNow
        """
        # First, get the sys_id for the incident number
        if ctx:
            await ctx.info(f"Looking up incident: {number}")
            
        incident = await self.client.get_incident_by_number(number)
        
        if not incident:
            error_message = f"Incident {number} not found"
            if ctx:
                await ctx.error(error_message)
            return json.dumps({"error": error_message})
            
        sys_id = incident['sys_id']
        
        # Now update the incident
        if ctx:
            await ctx.info(f"Updating incident: {number}")
            
        data = updates.dict(exclude_none=True)
        result = await self.client.update_record("incident", sys_id, data)
        
        return json.dumps(result, indent=2)
        
    async def search_records(self, 
                    query: str, 
                    table: str = "incident",
                    limit: int = 10,
                    ctx: Context = None) -> str:
        """
        Search for records in ServiceNow using text query
        
        Args:
            query: Text to search for
            table: Table to search in
            limit: Maximum number of results to return
            ctx: Optional context object for progress reporting
            
        Returns:
            JSON response containing matching records
        """
        if ctx:
            await ctx.info(f"Searching {table} for: {query}")

        # Use encoded query if it looks like a filter; else full-text
        encoded_markers = ["=", "^", "LIKE", "STARTSWITH", "ENDSWITH"]
        if any(marker in (query or "") for marker in encoded_markers):
            return await self.perform_query(table=table, query=query or "", limit=limit, ctx=ctx)

        result = await self.client.search(query, table, limit)

        # Fallbacks when full-text returns nothing
        try:
            no_results = not result or not result.get("result")
        except Exception:
            no_results = False

        if no_results:
            if ctx:
                await ctx.info("No results from full-text search, trying structured filters...")
            if table == "sys_user":
                # Try matching by display name or username
                enc = (
                    f"nameLIKE{query}^ORuser_nameLIKE{query}^ORemailLIKE{query}"
                )
                return await self.perform_query(table=table, query=enc, limit=limit, ctx=ctx)
            elif table == "incident":
                # Try common text fields for incidents
                enc = (
                    f"short_descriptionLIKE{query}^ORdescriptionLIKE{query}^ORcaller_id.nameLIKE{query}^ORopened_by.nameLIKE{query}^ORassigned_to.nameLIKE{query}"
                )
                return await self.perform_query(table=table, query=enc, limit=limit, ctx=ctx)

        return json.dumps(result, indent=2)
        
    async def get_record(self,
                table: str,
                sys_id: str,
                ctx: Context = None) -> str:
        """
        Get a specific record by sys_id
        
        Args:
            table: Table to query
            sys_id: System ID of the record
            ctx: Optional context object for progress reporting
            
        Returns:
            JSON response containing the record
        """
        if ctx:
            await ctx.info(f"Getting {table} record: {sys_id}")
            
        result = await self.client.get_record(table, sys_id)
        return json.dumps(result, indent=2)
        
    async def perform_query(self,
                   table: str,
                   query: str = "",
                   limit: int = 10,
                   offset: int = 0,
                   fields: Optional[List[str]] = None,
                   ctx: Context = None) -> str:
        """
        Perform a query against ServiceNow
        
        Args:
            table: Table to query
            query: Encoded query string (ServiceNow syntax)
            limit: Maximum number of results to return
            offset: Number of records to skip
            fields: List of fields to return (or all fields if None)
            ctx: Optional context object for progress reporting
            
        Returns:
            JSON response containing query results
        """
        if ctx:
            await ctx.info(f"Querying {table} with: {query}")
            
        # Normalize common incident user filters missing dot-walking
        if table == "incident" and query:
            query = self._normalize_incident_query(query)

        options = QueryOptions(
            limit=limit,
            offset=offset,
            fields=fields,
            query=query
        )
        
        result = await self.client.get_records(table, options)
        return json.dumps(result, indent=2)
        
    async def add_comment(self,
                 number: str,
                 comment: str,
                 ctx: Context = None) -> str:
        """
        Add a comment to an incident (customer visible)
        
        Args:
            number: Incident number
            comment: Comment to add
            ctx: Optional context object for progress reporting
            
        Returns:
            JSON response from ServiceNow
        """
        if ctx:
            await ctx.info(f"Adding comment to incident: {number}")
            
        incident = await self.client.get_incident_by_number(number)
        
        if not incident:
            error_message = f"Incident {number} not found"
            if ctx:
                await ctx.error(error_message)
            return json.dumps({"error": error_message})
            
        sys_id = incident['sys_id']
        
        # Add the comment
        update = {"comments": comment}
        result = await self.client.update_record("incident", sys_id, update)
        
        return json.dumps(result, indent=2)
        
    async def add_work_notes(self,
                    number: str,
                    work_notes: str,
                    ctx: Context = None) -> str:
        """
        Add work notes to an incident (internal)
        
        Args:
            number: Incident number
            work_notes: Work notes to add
            ctx: Optional context object for progress reporting
            
        Returns:
            JSON response from ServiceNow
        """
        if ctx:
            await ctx.info(f"Adding work notes to incident: {number}")
            
        incident = await self.client.get_incident_by_number(number)
        
        if not incident:
            error_message = f"Incident {number} not found"
            if ctx:
                await ctx.error(error_message)
            return json.dumps({"error": error_message})
            
        sys_id = incident['sys_id']
        
        # Add the work notes
        update = {"work_notes": work_notes}
        result = await self.client.update_record("incident", sys_id, update)
        
        return json.dumps(result, indent=2)
    
    # Prompt templates
    def incident_analysis_prompt(self, incident_number: str) -> str:
        """Create a prompt to analyze a ServiceNow incident
        
        Args:
            incident_number: The incident number to analyze (e.g., INC0010001)
            
        Returns:
            Prompt text for analyzing the incident
        """
        return f"""
        Please analyze the following ServiceNow incident {incident_number}.
        
        First, call the appropriate tool to fetch the incident details using get_incident.
        
        Then, provide a comprehensive analysis with the following sections:
        
        1. Summary: A brief overview of the incident
        2. Impact Assessment: Analysis of the impact based on the severity, priority, and affected users
        3. Root Cause Analysis: Potential causes based on available information
        4. Resolution Recommendations: Suggested next steps to resolve the incident
        5. SLA Status: Whether the incident is at risk of breaching SLAs
        
        Use a professional and clear tone appropriate for IT service management.
        """
        
    def create_incident_prompt(self) -> str:
        """Create a prompt for incident creation guidance
        
        Returns:
            Prompt text for helping users create an incident
        """
        return """
        I'll help you create a new ServiceNow incident. Please provide the following information:
        
        1. Short Description: A brief title for the incident (required)
        2. Detailed Description: A thorough explanation of the issue (required)
        3. Caller: The person reporting the issue (optional)
        4. Category and Subcategory: The type of issue (optional)
        5. Impact (1-High, 2-Medium, 3-Low): How broadly this affects users (optional)
        6. Urgency (1-High, 2-Medium, 3-Low): How time-sensitive this issue is (optional)
        
        After collecting this information, I'll use the create_incident tool to submit the incident to ServiceNow.
        """


# Factory functions for creating authentication objects
def create_basic_auth(username: str, password: str) -> BasicAuth:
    """Create BasicAuth object for ServiceNow authentication"""
    return BasicAuth(username, password)

def create_token_auth(token: str) -> TokenAuth:
    """Create TokenAuth object for ServiceNow authentication"""
    return TokenAuth(token)

def create_oauth_auth(client_id: str, client_secret: str, 
                     username: str, password: str,
                     instance_url: str) -> OAuthAuth:
    """Create OAuthAuth object for ServiceNow authentication"""
    return OAuthAuth(client_id, client_secret, username, password, instance_url)

# Main function for running the server from the command line
def main():
    """Run the ServiceNow MCP server from the command line"""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")
    parser.add_argument("--url", help="ServiceNow instance URL", default=os.environ.get("SERVICENOW_INSTANCE_URL"))
    parser.add_argument("--transport", help="Transport protocol (stdio or sse)", default="stdio", choices=["stdio", "sse"])
    
    # Authentication options
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument("--username", help="ServiceNow username", default=os.environ.get("SERVICENOW_USERNAME"))
    auth_group.add_argument("--password", help="ServiceNow password", default=os.environ.get("SERVICENOW_PASSWORD"))
    auth_group.add_argument("--token", help="ServiceNow token", default=os.environ.get("SERVICENOW_TOKEN"))
    auth_group.add_argument("--client-id", help="OAuth client ID", default=os.environ.get("SERVICENOW_CLIENT_ID"))
    auth_group.add_argument("--client-secret", help="OAuth client secret", default=os.environ.get("SERVICENOW_CLIENT_SECRET"))
    
    args = parser.parse_args()
    
    # Check required parameters
    if not args.url:
        print("Error: ServiceNow instance URL is required")
        print("Set SERVICENOW_INSTANCE_URL environment variable or use --url")
        sys.exit(1)
    
    # Determine authentication method
    auth = None
    if args.token:
        auth = create_token_auth(args.token)
    elif args.client_id and args.client_secret and args.username and args.password:
        auth = create_oauth_auth(args.client_id, args.client_secret, args.username, args.password, args.url)
    elif args.username and args.password:
        auth = create_basic_auth(args.username, args.password)
    else:
        print("Error: Authentication credentials required")
        print("Either provide username/password, token, or OAuth credentials")
        sys.exit(1)
    
    # Create and run the server
    server = ServiceNowMCP(instance_url=args.url, auth=auth)
    server.run(transport=args.transport)

# Entry point
if __name__ == "__main__":
    main()
