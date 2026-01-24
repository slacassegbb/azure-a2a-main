# Image Display Fix - Why Workflow Sidebar Worked But Main Chat Didn't

## Problem Summary

Generated images from the Image Generator agent appeared in the **"Show Agent Workflow" sidebar** but NOT in the **main chat window**.

---

## Root Cause: Two Separate Event Paths

The frontend has **two different systems** for displaying agent outputs:

### 1. **Workflow Sidebar** (✅ Was Working)
- **Event Source**: `file_uploaded` event
- **Flow**: Image Generator → Uploads to blob → Backend emits `file_uploaded` event → Workflow sidebar displays image
- **Code Location**: `frontend/components/chat-panel.tsx` lines 1383-1398
- **Data Included**: Full file info with `uri`, `filename`, `content_type`, `source_agent`

```typescript
const handleFileUploaded = (data: any) => {
  console.log("[ChatPanel] File uploaded from agent:", data)
  if (data?.fileInfo && data.fileInfo.source_agent) {
    const isImage = data.fileInfo.content_type?.startsWith('image/')
    
    // Add to inference steps (with thumbnail for images)
    setInferenceSteps(prev => [...prev, { 
      agent: data.fileInfo.source_agent, 
      status: `📎 Generated ${data.fileInfo.filename}`,
      imageUrl: isImage && data.fileInfo.uri ? data.fileInfo.uri : undefined,
      imageName: data.fileInfo.filename
    }])
  }
}
```

### 2. **Main Chat Window** (❌ Was Broken)
- **Event Source**: `message` event
- **Flow**: Image Generator → Sends message with FilePart → Backend extracts content via `_extract_message_content()` → Main chat displays message
- **Code Location**: `backend/service/websocket_streamer.py` lines 392-431
- **Problem**: The `_extract_message_content()` method was NOT extracting image URIs from FilePart objects

**Before Fix:**
```python
elif hasattr(part, 'file') and part.file:
    content.append({
        "type": "file",
        "content": f"File: {getattr(part.file, 'name', 'unknown')}"
    })
```
This only included the filename as text, NOT the actual URI!

---

## The Fix

### Backend Fix: `backend/service/websocket_streamer.py`

Updated `_extract_message_content()` to properly extract image URIs from FilePart:

```python
elif hasattr(part, 'file') and part.file:
    file_obj = part.file
    file_dict = {
        "type": "file",
        "content": f"File: {getattr(file_obj, 'name', 'unknown')}"
    }
    # Include URI if available (for images and other files)
    if hasattr(file_obj, 'uri') and file_obj.uri:
        file_dict["uri"] = str(file_obj.uri)
        file_dict["fileName"] = getattr(file_obj, 'name', 'unknown')
        # Check if it's an image based on URI or mimeType
        mime_type = getattr(file_obj, 'mimeType', '')
        if mime_type.startswith('image/') or any(ext in str(file_obj.uri).lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
            file_dict["type"] = "image"
    content.append(file_dict)
```

### Frontend Fix: `frontend/components/chat-panel.tsx`

Already fixed in previous commit (lines 1031-1045 and 1488-1497) to pass images through from message content to final display.

---

## Why This Matters

The `file_uploaded` event is emitted during streaming as files are created, while the `message` event contains the complete response with all parts (text + files). 

- **Workflow sidebar** = Real-time file tracking (shows files as they're created)
- **Main chat** = Complete message display (shows final response with all content)

Both need to work for a complete user experience!

---

## Testing After Deployment

1. Push changes to trigger GitHub Actions deployment
2. Wait for backend to redeploy with the fix
3. Test with: `"generate an image of a dog"`
4. Verify image appears in:
   - ✅ Workflow sidebar (already working)
   - ✅ Main chat window (should now work)
   - ✅ File history (should work)

---

## Commits Applied

1. **e7e6a36**: `fix: Include images inline with host agent response in main chat` (Frontend)
2. **f49e766**: `fix: Extract image URIs from FilePart in WebSocket message content` (Backend)

Both fixes are required for images to display properly in the main chat!
