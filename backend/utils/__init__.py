"""Backend Utilities Module"""

from .tenant import (
    create_context_id,
    parse_context_id,
    get_tenant_from_context,
    get_conversation_from_context,
    generate_tenant_id,
    is_tenant_aware_context,
    get_tenant_file_path,
    TENANT_SEPARATOR,
)

from .file_parts import (
    extract_uri,
    extract_filename,
    extract_mime_type,
    create_file_part,
    is_file_part,
    is_image_part,
    extract_all_images,
    convert_artifact_dict_to_file_part,
)

__all__ = [
    # Tenant utils
    "create_context_id",
    "parse_context_id", 
    "get_tenant_from_context",
    "get_conversation_from_context",
    "generate_tenant_id",
    "is_tenant_aware_context",
    "get_tenant_file_path",
    "TENANT_SEPARATOR",
    # File parts utils
    "extract_uri",
    "extract_filename",
    "extract_mime_type",
    "create_file_part",
    "is_file_part",
    "is_image_part",
    "extract_all_images",
    "convert_artifact_dict_to_file_part",
]
