#!/usr/bin/env python3

import os
import re
import sys
import concurrent.futures
import uuid
import platform
import subprocess
from functools import partial
from datetime import datetime, timezone
from pathlib import Path
import json

# Utils - using the user's proven working imports
from . import doc2md_utils
from .content_understanding_client import AzureContentUnderstandingClient

# Import the A2A memory service
from .a2a_memory_service import a2a_memory_service

# Runtime directory for generated files
RUNTIME_DIR = Path(__file__).resolve().parents[2] / ".runtime"

# Paths - from user's original code (now under .runtime/)
image_path = str(RUNTIME_DIR / 'images')
markdown_path = str(RUNTIME_DIR / 'markdown')
json_path = 'json'

# File extensions - from user's original code
AUDIO_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.flac', '.aac']
VIDEO_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']
DOCUMENT_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.xlsx', '.doc', '.ppt', '.xls']
TEXT_EXTENSIONS = ['.txt', '.md', '.json', '.xml', '.csv', '.html', '.htm', '.js', '.py', '.java', '.c', '.cpp', '.h', '.yaml', '.yml', '.log', '.sh', '.bat', '.ps1', '.sql', '.css']

# Azure Content Understanding configuration
def get_content_understanding_client():
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    
    # Create credentials using exactly the same approach as in the user's code
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
    
    azure_ai_service_endpoint = (
        os.getenv("AZURE_CONTENT_UNDERSTANDING_ENDPOINT")
        or os.getenv("AZURE_AI_SERVICE_ENDPOINT")
    )
    if not azure_ai_service_endpoint:
        print("⚠️ Missing AZURE_CONTENT_UNDERSTANDING_ENDPOINT (or AZURE_AI_SERVICE_ENDPOINT) environment variable.")
        return None

    azure_ai_service_endpoint = azure_ai_service_endpoint.strip().rstrip("/")

    azure_ai_service_api_version = os.getenv(
        "AZURE_CONTENT_UNDERSTANDING_API_VERSION",
        "2024-12-01-preview",
    )
    
    print(f"Azure Content Understanding endpoint: {azure_ai_service_endpoint}")
    print(f"Azure Content Understanding API version: {azure_ai_service_api_version}")

    try:
        # Create client with the exact same parameters as in the user's code
        client = AzureContentUnderstandingClient(
            endpoint=azure_ai_service_endpoint,
            api_version=azure_ai_service_api_version,
            token_provider=token_provider,
            x_ms_useragent="azure-ai-content-understanding-python/content_extraction"
        )
        
        return client
    except Exception as e:
        print(f"Error initializing Content Understanding client: {e}")
        return None

def sanitize_doc_id(doc_id):
    """Replace invalid characters in document IDs with valid ones for Azure Search."""
    # Replace periods with underscores
    return doc_id.replace('.', '_')

def determine_file_type(file_path):
    """Determine the type of file based on its extension."""
    _, extension = os.path.splitext(file_path.lower())
    
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    elif extension in VIDEO_EXTENSIONS:
        return "video"
    elif extension in IMAGE_EXTENSIONS:
        return "image"
    elif extension in DOCUMENT_EXTENSIONS:
        return "document"
    elif extension in TEXT_EXTENSIONS:
        return "text"
    else:
        return "unknown"

def text_to_speech(text: str, output_path: str = None) -> str:
    """Convert text to speech and save as mp3 - from user's original code"""
    if output_path is None:
        output_path = f"temp_speech_{uuid.uuid4()}.mp3"
        
    system = platform.system()
    try:
        if system == 'Darwin':  # macOS
            subprocess.run(['say', '-o', output_path, '--file-format=mp4af', text])
        elif system == 'Windows':
            powershell_cmd = f'''
            Add-Type -AssemblyName System.Speech
            $synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
            $synthesizer.SetOutputToWaveFile("{output_path}")
            $synthesizer.Speak("{text}")
            $synthesizer.Dispose()
            '''
            subprocess.run(['powershell', '-command', powershell_cmd], shell=True)
        elif system == 'Linux':
            subprocess.run(['espeak', '-w', output_path, text])
            
        return output_path
            
    except Exception as e:
        print(f"Error in text_to_speech: {e}")
        return None

def process_audio(audio_path: str, return_text: bool = False):
    """
    Process audio file - from user's original working code.
    If return_text is True, returns the transcript text instead of JSON file paths.
    """
    print(f"Processing audio: {audio_path}")
    client = get_content_understanding_client()
    
    if client is None:
        print("Content Understanding client not available. Skipping audio processing.")
        return None if return_text else []
    
    analyzer_id = f"audio-analyzer-{str(uuid.uuid4())}"
    
    try:
        # Create the audio analyzer using the template
        response = client.begin_create_analyzer(
            analyzer_id=analyzer_id,
            analyzer_template_path="analyzer_templates/audio_transcription.json"
        )
        result = client.poll_result(response)
        print(f"Successfully created analyzer: {analyzer_id}")
        
        # Analyze the audio content
        print(f"[DEBUG] Starting analysis of audio file: {audio_path}")
        response = client.begin_analyze(analyzer_id, audio_path)
        print(f"[DEBUG] Analysis request sent, polling for results...")
        result = client.poll_result(response)
        print(f"Successfully analyzed audio with analyzer: {analyzer_id}")
        print(f"[DEBUG] Analysis result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
        
        # Extract transcript from the result
        audio_content = result["result"]
        transcript = ""
        summary = ""
        
        if "contents" in audio_content and len(audio_content["contents"]) > 0:
            content = audio_content["contents"][0]
            
            # Extract summary if available
            if "fields" in content and "Summary" in content["fields"]:
                summary = content["fields"]["Summary"]["valueString"]
            
            # Extract full transcript
            if "transcriptPhrases" in content:
                for phrase in content["transcriptPhrases"]:
                    if "speaker" in phrase and "text" in phrase:
                        transcript += f"{phrase['text']} "  # Just get text without speaker for TTS
        
        # Cleanup
        client.delete_analyzer(analyzer_id)
        
        if return_text:
            return transcript.strip()
        
        # Create full content for A2A memory
        full_content = f"Audio file: {os.path.basename(audio_path)}\n\n"
        if summary:
            full_content += f"Summary: {summary}\n\n"
        full_content += f"Transcript:\n{transcript}"
        
        return full_content
            
    except Exception as e:
        print(f"Error processing audio: {e}")
        print(f"Error type: {type(e).__name__}")
        
        # Try to get more details from the exception
        if hasattr(e, 'response'):
            print(f"HTTP Response status: {e.response.status_code}")
            try:
                print(f"HTTP Response body: {e.response.text}")
            except:
                print("Could not get response body")
        
        # If it's a RuntimeError from poll_result, try to extract more info
        if isinstance(e, RuntimeError) and "Request failed" in str(e):
            print("This is a RuntimeError from Azure Content Understanding service")
            print("The actual error details should be in the Azure service logs")
        
        try:
            client.delete_analyzer(analyzer_id)
        except Exception as cleanup_error:
            print(f"Error during cleanup: {cleanup_error}")
        
        return None if return_text else []

def process_video(video_path):
    """Process video files - from user's original working code"""
    print(f"Processing video: {video_path}")
    client = get_content_understanding_client()
    
    # Check if client is available
    if client is None:
        print("Content Understanding client not available. Skipping video processing.")
        return []
    
    # Create a unique analyzer ID for the video
    analyzer_id = f"video-analyzer-{str(uuid.uuid4())}"
    
    try:
        # Create the video analyzer using the template
        # Get the directory where this module is located
        module_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(module_dir, "analyzer_templates", "video_content_understanding.json")
        print(f"Looking for video analyzer template at: {template_path}")
        
        response = client.begin_create_analyzer(
            analyzer_id=analyzer_id,
            analyzer_template_path=template_path
        )
        result = client.poll_result(response)
        print(f"Successfully created analyzer: {analyzer_id}")
        
        # Analyze the video content
        response = client.begin_analyze(analyzer_id, video_path)
        result = client.poll_result(response)
        print(f"Successfully analyzed video with analyzer: {analyzer_id}")
        
        # Process the results
        video_content = result["result"]["contents"]
        
        full_content = f"Video file: {os.path.basename(video_path)}\n\n"
        
        for i, content in enumerate(video_content):
            # Extract relevant information
            if "fields" in content and "segmentDescription" in content["fields"]:
                description = content["fields"]["segmentDescription"]["valueString"]
            else:
                description = ""
                
            transcript = ""
            if "transcriptPhrases" in content:
                for phrase in content["transcriptPhrases"]:
                    if "text" in phrase:
                        transcript += f"{phrase['text']} "
            
            # Create content for this segment
            time_range = f"{content['startTimeMs']/1000:.1f}s-{content['endTimeMs']/1000:.1f}s"
            
            full_content += f"Video Segment {time_range}: {description}\n\nTranscript: {transcript}\n\n"
        
        # Cleanup
        client.delete_analyzer(analyzer_id)
        return full_content
        
    except Exception as e:
        print(f"Error processing video: {e}")
        # Try to clean up analyzer even if there was an error
        try:
            client.delete_analyzer(analyzer_id)
        except:
            pass
        return []

def process_document(document_path):
    """Process document files - from user's original working code"""
    print(f"Processing document: {document_path}")
    
    # Convert file to PDF
    pdf_path = doc2md_utils.convert_to_pdf(document_path)
    if not pdf_path:
        print(f"Error: Could not convert {document_path} to PDF")
        return []

    # Extract PDF pages to images
    doc_id = doc2md_utils.extract_pdf_pages_to_images(pdf_path, image_path)
    pdf_images_dir = os.path.join(image_path, doc_id)
    files = doc2md_utils.get_all_files(pdf_images_dir)
    print(f'Total Image Files to Process: {len(files)}')

    # Convert images to markdown in parallel
    markdown_out_dir = os.path.join(markdown_path, doc_id)
    doc2md_utils.ensure_directory_exists(markdown_out_dir)
    
    partial_process_image = partial(doc2md_utils.process_image, markdown_out_dir=markdown_out_dir)
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(partial_process_image, files))
    
    # Get markdown files exactly like in the user's code
    files = os.listdir(markdown_out_dir)
    txt_files = [f for f in files if f.endswith('.txt')]
    print(f'Total Markdown Files: {len(txt_files)}')
    
    # Combine all markdown content
    combined_content = ""
    for txt_file in sorted(txt_files):
        txt_path = os.path.join(markdown_out_dir, txt_file)
        with open(txt_path, 'r', encoding='utf-8') as f:
            combined_content += f.read() + "\n\n"
    
    return combined_content

def process_image(image_path):
    """Process a single image file - from user's original working code"""
    print(f"Processing image: {image_path}")
    
    # Convert the image to markdown using existing utility
    markdown_text = doc2md_utils.extract_markdown_from_image(image_path)
    
    return markdown_text

def process_text_file(text_file_path):
    """
    Process a text-based file directly - from user's original working code.
    """
    print(f"Processing text-based file: {text_file_path}")
    
    try:
        # Try to read the file as text with different encodings
        text_content = None
        encodings = ['utf-8', 'latin-1', 'cp1252', 'ascii']
        
        for encoding in encodings:
            try:
                with open(text_file_path, 'r', encoding=encoding) as f:
                    text_content = f.read()
                print(f"Successfully read file with {encoding} encoding")
                break
            except UnicodeDecodeError:
                continue
        
        if text_content is None:
            # If all text encodings fail, try binary mode for special formats
            with open(text_file_path, 'rb') as f:
                binary_content = f.read()
                
            # Try to decode JSON if it's a binary JSON file
            if text_file_path.lower().endswith('.json'):
                try:
                    parsed = json.loads(binary_content)
                    text_content = json.dumps(parsed, indent=2)
                except:
                    text_content = binary_content.decode('utf-8', errors='replace')
            else:
                # Fall back to replacing invalid characters
                text_content = binary_content.decode('utf-8', errors='replace')
        
        return text_content
        
    except Exception as e:
        print(f"Error processing text file: {e}")
        import traceback
        print(traceback.format_exc())
        return ""

def process_file(file_path):
    """Process a file based on its type - from user's original working code"""
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist")
        return ""
    
    file_type = determine_file_type(file_path)
    
    # Convert to absolute path for processing
    abs_file_path = os.path.abspath(file_path)
    print(f"Processing {file_type} file: {abs_file_path}")
    
    if file_type == "audio":
        return process_audio(abs_file_path, return_text=True)
    elif file_type == "video":
        return process_video(abs_file_path)
    elif file_type == "image":
        return process_image(abs_file_path)
    elif file_type == "document":
        # Special handling for .txt files
        if abs_file_path.lower().endswith('.txt'):
            return process_text_file(abs_file_path)
        else:
            return process_document(abs_file_path)
    elif file_type == "text":
        return process_text_file(abs_file_path)
    else:
        print(f"Error: Unsupported file type for {abs_file_path}")
        return ""

# A2A Integration Function
async def process_file_part(file_part, artifact_info=None, session_id: str = None):
    """
    Process a file part from A2A and store the extracted content in A2A memory service.
    This is the main entry point called by the host agent.
    
    Args:
        file_part: The file part from A2A message
        artifact_info: Optional artifact metadata
        session_id: Session ID for tenant isolation (required for multi-tenancy)
    """
    try:
        # Extract file information
        filename = getattr(file_part, 'name', f'unknown_file_{uuid.uuid4()}')
        if artifact_info and 'file_name' in artifact_info:
            filename = artifact_info['file_name']
        print(f"[A2ADocumentProcessor] Processing file: {filename}")
        
        filename_lower = filename.lower()
        if "-mask" in filename_lower or "_mask" in filename_lower:
            print(f"[A2ADocumentProcessor] Skipping mask file {filename}")
            return {
                "success": True,
                "content": "",
                "filename": filename,
                "file_type": determine_file_type(filename),
                "skipped": True,
                "reason": "mask file"
            }

        # Save file temporarily for processing
        import tempfile
        import os
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{filename}")
        
        # Get file bytes - handle both direct bytes and Azure Blob URIs
        file_bytes = None
        
        # First, try to get file bytes directly from file_part
        if hasattr(file_part, 'data'):
            file_bytes = file_part.data
        elif hasattr(file_part, 'bytes'):
            file_bytes = file_part.bytes
        elif hasattr(file_part, 'content'):
            file_bytes = file_part.content
        
        # If no direct bytes, check if we have file bytes in artifact_info or need to download
        if file_bytes is None and artifact_info:
            # First check if file bytes are directly available (for local files)
            if 'file_bytes' in artifact_info:
                file_bytes = artifact_info['file_bytes']
                print(f"[A2ADocumentProcessor] Using file bytes from artifact_info: {len(file_bytes)} bytes")
            elif 'artifact_uri' in artifact_info:
                artifact_uri = artifact_info['artifact_uri']
                
                # Check if it's an Azure Blob URI (contains blob.core.windows.net)
                if 'blob.core.windows.net' in artifact_uri:
                    print(f"[A2ADocumentProcessor] Downloading file from Azure Blob: {artifact_uri}")
                    
                    try:
                        import requests
                        response = requests.get(artifact_uri)
                        response.raise_for_status()
                        file_bytes = response.content
                        print(f"[A2ADocumentProcessor] Downloaded {len(file_bytes)} bytes from Azure Blob")
                    except Exception as e:
                        print(f"[A2ADocumentProcessor] Error downloading from Azure Blob: {e}")
                        return {"success": False, "error": f"Failed to download from Azure Blob: {e}"}
                else:
                    print(f"[A2ADocumentProcessor] Unknown URI type (not Azure Blob): {artifact_uri}")
                    return {"success": False, "error": "Unknown URI type (not Azure Blob)"}
        
        if file_bytes is None:
            print(f"[A2ADocumentProcessor] Could not find file bytes in file part or artifact URI")
            return {"success": False, "error": "Could not find file bytes"}
        
        # Write to temporary file
        with open(temp_file_path, 'wb') as f:
            f.write(file_bytes)
        
        # Process the file using the user's proven working logic
        processed_content = process_file(temp_file_path)
        
        # Clean up temporary file
        try:
            os.remove(temp_file_path)
        except:
            pass
        
        if not processed_content:
            print(f"[A2ADocumentProcessor] No content extracted from file")
            return {"success": False, "error": "No content extracted"}
        
        processed_content = _strip_markdown_fences(processed_content)
        
        # Create A2A-compliant interaction structure
        interaction_data = {
            "agent_name": "DocumentProcessor",
            "task_id": artifact_info.get('task_id') if artifact_info else str(uuid.uuid4()),
            "artifact_id": artifact_info.get('id') if artifact_info else str(uuid.uuid4()),
            "filename": filename,
            "outbound_payload": {
                "type": "document_processing_request",
                "filename": filename,
                "file_type": determine_file_type(filename),
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "inbound_payload": {
                "type": "document_processing_result",
                "filename": filename,  # Include filename for memory service lookup
                "content": processed_content,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "success": True
            }
        }
        
        # Store the interaction in A2A memory service
        if session_id:
            await a2a_memory_service.store_interaction(interaction_data, session_id=session_id)
            print(f"[A2ADocumentProcessor] Successfully processed and stored: {filename} (session: {session_id})")
        else:
            print(f"[A2ADocumentProcessor] Warning: No session_id, skipping memory storage for {filename}")
        
        print(f"[A2ADocumentProcessor] Content length: {len(processed_content)} characters")
        
        # Return both success status AND the extracted content for immediate use
        return {
            "success": True,
            "content": _strip_markdown_fences(processed_content),
            "filename": filename,
            "file_type": determine_file_type(filename)
        }
        
    except Exception as e:
        print(f"[A2ADocumentProcessor] Error processing file: {e}")
        import traceback
        print(f"[A2ADocumentProcessor] Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}

# Class wrapper for compatibility
class A2ADocumentProcessor:
    """A2A Document Processor using the user's proven working implementation"""
    
    async def process_file_part(self, file_part, artifact_info=None, session_id: str = None):
        """Process file part - delegates to the main function"""
        processed_content = await process_file_part(file_part, artifact_info, session_id=session_id)
        return _strip_markdown_fences(processed_content)


def _strip_markdown_fences(content: str) -> str:
    """Remove common ```markdown fences and standalone triple backticks."""
    if not isinstance(content, str):
        return content

    cleaned = content.strip()

    # Remove "```markdown" markers and standalone ``` fences
    cleaned = re.sub(r"```(?:markdown)?", "", cleaned, flags=re.IGNORECASE)
    # Collapse excess whitespace introduced by removals
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()

# Create instance for import
a2a_document_processor = A2ADocumentProcessor() 