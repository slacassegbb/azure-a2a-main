"""
File Parts Utility Module

Standardizes file exchange across the A2A system using FilePart with FileWithUri.
This is the ONLY pattern for file references - no DataPart with artifact-uri.

Usage:
    from utils.file_parts import extract_uri, create_file_part, is_image_part

    # Extract URI from any part type
    uri = extract_uri(part)
    
    # Create a FilePart from a blob URL
    file_part = create_file_part(uri="https://blob.url/image.png", name="image.png")
    
    # Check if a part is an image
    if is_image_part(part):
        images.append(extract_uri(part))
"""

from typing import Optional, Any, List
from a2a.types import Part, FilePart, FileWithUri, DataPart, TextPart


def extract_uri(part: Any) -> Optional[str]:
    """
    Extract URI from any A2A Part type.
    
    Handles:
    - FilePart with FileWithUri (preferred)
    - Part(root=FilePart(...))
    - DataPart with artifact-uri (legacy, for backward compat)
    - Part(root=DataPart(...))
    
    Returns None if no URI found.
    """
    if part is None:
        return None
    
    # Unwrap Part.root if present
    target = getattr(part, 'root', part)
    
    # FilePart with FileWithUri (preferred format)
    if isinstance(target, FilePart):
        file_obj = getattr(target, 'file', None)
        if file_obj and hasattr(file_obj, 'uri'):
            uri = file_obj.uri
            if uri and str(uri).startswith(('http://', 'https://')):
                return str(uri)
    
    # Legacy: DataPart with artifact-uri
    if isinstance(target, DataPart) and isinstance(target.data, dict):
        uri = target.data.get('artifact-uri') or target.data.get('uri')
        if uri and str(uri).startswith(('http://', 'https://')):
            return str(uri)
    
    return None


def extract_filename(part: Any) -> Optional[str]:
    """Extract filename from any A2A Part type."""
    if part is None:
        return None
    
    target = getattr(part, 'root', part)
    
    if isinstance(target, FilePart):
        file_obj = getattr(target, 'file', None)
        if file_obj:
            return getattr(file_obj, 'name', None)
    
    if isinstance(target, DataPart) and isinstance(target.data, dict):
        return target.data.get('file-name') or target.data.get('name')
    
    return None


def extract_mime_type(part: Any) -> str:
    """Extract MIME type from any A2A Part type, defaults to image/png."""
    if part is None:
        return 'image/png'
    
    target = getattr(part, 'root', part)
    
    if isinstance(target, FilePart):
        file_obj = getattr(target, 'file', None)
        if file_obj:
            return getattr(file_obj, 'mimeType', 'image/png') or 'image/png'
    
    if isinstance(target, DataPart) and isinstance(target.data, dict):
        return target.data.get('media-type') or target.data.get('mimeType') or 'image/png'
    
    return 'image/png'


def create_file_part(uri: str, name: str = 'artifact', mime_type: str = 'image/png') -> Part:
    """
    Create a standard A2A FilePart with FileWithUri.
    
    This is the canonical way to create file references in the system.
    """
    file_with_uri = FileWithUri(
        name=name,
        uri=uri,
        mimeType=mime_type
    )
    return Part(root=FilePart(file=file_with_uri))


def is_file_part(part: Any) -> bool:
    """Check if a part is a FilePart (contains file reference)."""
    if part is None:
        return False
    target = getattr(part, 'root', part)
    return isinstance(target, FilePart)


def is_image_part(part: Any) -> bool:
    """Check if a part is an image file."""
    uri = extract_uri(part)
    if not uri:
        return False
    
    mime_type = extract_mime_type(part)
    if mime_type.startswith('image/'):
        return True
    
    # Check file extension
    uri_lower = uri.lower().split('?')[0]  # Remove query params
    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff')
    return uri_lower.endswith(image_extensions)


def extract_all_images(parts: List[Any]) -> List[dict]:
    """
    Extract all images from a list of parts.
    
    Returns list of dicts with uri, fileName, mediaType.
    """
    images = []
    for part in parts:
        if is_image_part(part):
            uri = extract_uri(part)
            if uri:
                images.append({
                    'uri': uri,
                    'fileName': extract_filename(part) or 'image.png',
                    'mediaType': extract_mime_type(part)
                })
    return images


def convert_artifact_dict_to_file_part(artifact: dict) -> Optional[Part]:
    """
    Convert legacy artifact dict to FilePart.
    
    Use this when receiving {"artifact-uri": "...", "file-name": "...", ...}
    to convert to the standard FilePart format.
    """
    uri = artifact.get('artifact-uri')
    if not uri:
        return None
    
    return create_file_part(
        uri=uri,
        name=artifact.get('file-name', 'artifact'),
        mime_type=artifact.get('media-type', artifact.get('mime', 'image/png'))
    )
