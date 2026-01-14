"""Tenant Utilities for Multi-Tenancy Support

This module provides utilities for tenant isolation by leveraging
the A2A protocol's contextId field. The contextId format is:
    tenant_id::conversation_id

This allows tenant extraction without breaking A2A protocol compatibility.
"""

import uuid
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Separator used to encode tenant_id in contextId
TENANT_SEPARATOR = "::"


def create_context_id(tenant_id: str, conversation_id: Optional[str] = None) -> str:
    """Create a tenant-aware contextId for A2A protocol.
    
    Args:
        tenant_id: Unique identifier for the tenant/session
        conversation_id: Optional conversation ID (generates new UUID if not provided)
        
    Returns:
        Context ID in format: tenant_id::conversation_id
        
    Example:
        >>> create_context_id("sess_abc123", "conv_xyz789")
        'sess_abc123::conv_xyz789'
        >>> create_context_id("sess_abc123")
        'sess_abc123::a1b2c3d4-e5f6-...'
    """
    conv_id = conversation_id or str(uuid.uuid4())
    context_id = f"{tenant_id}{TENANT_SEPARATOR}{conv_id}"
    logger.debug(f"Created context_id: {context_id[:50]}...")
    return context_id


def parse_context_id(context_id: str) -> Tuple[str, str]:
    """Parse a contextId to extract tenant_id and conversation_id.
    
    Args:
        context_id: The context ID to parse
        
    Returns:
        Tuple of (tenant_id, conversation_id)
        
    Note:
        If context_id doesn't contain separator, treats entire ID as
        conversation_id with an anonymous tenant prefix.
        
    Example:
        >>> parse_context_id("sess_abc123::conv_xyz789")
        ('sess_abc123', 'conv_xyz789')
        >>> parse_context_id("legacy-uuid-without-tenant")
        ('anon_legacy-uuid-without-tenant', 'legacy-uuid-without-tenant')
    """
    if TENANT_SEPARATOR in context_id:
        parts = context_id.split(TENANT_SEPARATOR, 1)
        tenant_id = parts[0]
        conversation_id = parts[1] if len(parts) > 1 else context_id
    else:
        # Legacy format - no tenant encoded, create anonymous tenant
        tenant_id = f"anon_{context_id}"
        conversation_id = context_id
        logger.debug(f"Legacy context_id format detected, using anonymous tenant")
    
    return tenant_id, conversation_id


def get_tenant_from_context(context_id: str) -> str:
    """Extract tenant_id from a contextId.
    
    Args:
        context_id: The context ID to extract tenant from
        
    Returns:
        The tenant_id portion of the context
        
    Example:
        >>> get_tenant_from_context("sess_abc123::conv_xyz789")
        'sess_abc123'
    """
    tenant_id, _ = parse_context_id(context_id)
    return tenant_id


def get_conversation_from_context(context_id: str) -> str:
    """Extract conversation_id from a contextId.
    
    Args:
        context_id: The context ID to extract conversation from
        
    Returns:
        The conversation_id portion of the context
        
    Example:
        >>> get_conversation_from_context("sess_abc123::conv_xyz789")
        'conv_xyz789'
    """
    _, conversation_id = parse_context_id(context_id)
    return conversation_id


def generate_tenant_id() -> str:
    """Generate a new unique tenant ID.
    
    Returns:
        A new tenant ID in format: sess_<uuid>
        
    Example:
        >>> generate_tenant_id()
        'sess_a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    """
    return f"sess_{uuid.uuid4()}"


def is_tenant_aware_context(context_id: str) -> bool:
    """Check if a contextId contains tenant information.
    
    Args:
        context_id: The context ID to check
        
    Returns:
        True if contextId contains tenant separator
        
    Example:
        >>> is_tenant_aware_context("sess_abc::conv_xyz")
        True
        >>> is_tenant_aware_context("legacy-uuid")
        False
    """
    return TENANT_SEPARATOR in context_id


def get_tenant_file_path(tenant_id: str, base_path: str, filename: str) -> str:
    """Get a tenant-scoped file path.
    
    Args:
        tenant_id: The tenant identifier
        base_path: Base directory path (e.g., "/app/uploads")
        filename: The filename
        
    Returns:
        Full path with tenant isolation: base_path/tenant_id/filename
        
    Example:
        >>> get_tenant_file_path("sess_abc123", "/app/uploads", "image.png")
        '/app/uploads/sess_abc123/image.png'
    """
    import os
    return os.path.join(base_path, tenant_id, filename)
