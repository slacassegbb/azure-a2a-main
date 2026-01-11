# 🎬 Sora 2 Video Generation Agent

**Generate stunning AI videos from text, images, or existing videos using Azure OpenAI's Sora 2 model.**

This agent provides a complete video generation solution that integrates with the Azure A2A multi-agent system. Create cinematic scenes, product demos, animations, and creative visual content with natural language descriptions.

---

## ✨ Features

- 🎥 **Text-to-Video** – Generate videos from natural language prompts
- 🖼️ **Image-to-Video** – Transform static images into dynamic videos (auto-resizing supported)
- 🔄 **Video Remix** – Modify previously generated videos while preserving core elements
- 📐 **Multiple Resolutions** – Support for landscape (1280x720) and portrait (720x1280)
- ⏱️ **Flexible Durations** – Generate 4, 8, or 12 second videos
- 💬 **Unified Chat Interface** – All modes accessible from a single chat UI
- 📡 **A2A Protocol Support** – Works with the Azure A2A orchestrator
- 🔊 **Audio Generation** – Videos include AI-generated audio

---

## 🚀 Quick Start

### 1. Set Up Environment

```bash
cd remote_agents/azurefoundry_video

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install uv
uv pip install -r ../../backend/requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Required: Azure AI Foundry Project
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/

# Optional: Override Azure OpenAI endpoint (auto-derived from above if not set)
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/

# Optional: Custom ports
A2A_PORT=9020
A2A_ENDPOINT=localhost

# Optional: Host agent auto-registration
HOST_AGENT_URL=http://localhost:12000
```

### 3. Run the Agent

**With Gradio UI (Recommended for video generation):**
```bash
uv run . --ui
```

Access the chat interface at: `http://localhost:9120`

**A2A Server Only:**
```bash
uv run .
```

---

## 🎬 Using the Video Generation UI

The unified chat interface provides all video generation modes in one place.

### Interface Overview

| Component | Description |
|-----------|-------------|
| **Chat Panel** | Main chat area with inline video display |
| **Mode Selector** | Auto-detect, Text-to-Video, Image-to-Video, or Remix |
| **Resolution** | 1280x720 (Landscape) or 720x1280 (Portrait) |
| **Duration** | 4, 8, or 12 seconds |
| **Image Upload** | Drag-and-drop for Image-to-Video mode |
| **Remix Video ID** | Enter video ID for remix mode |

### Generation Modes

#### 📝 Text-to-Video
Simply type your prompt and click Send:
```
A cinematic shot of a golden retriever running through a sunlit meadow at sunset, 
with gentle lens flare and slow motion, shot on 35mm film
```

#### 🖼️ Image-to-Video
1. Drag and drop an image into the chat
2. Describe the motion you want:
```
Gentle wind blowing through the trees, leaves rustling, with subtle camera movement
```

The image will be automatically resized to match your selected video resolution.

#### 🔄 Video Remix
1. Copy the Video ID from a previous generation (format: `video_abc123...`)
2. Paste it in the "Remix Video ID" field, OR include it in your message:
```
video_69276a126b60819082f97176ea0a3381: change the color palette to warm sunset tones
```
3. Enter your modification prompt

**Important:** Use the full Video ID (starts with `video_` + 32 hex characters), not the filename.

---

## 💡 Prompt Writing Tips

### Best Practices

| Element | Description | Example |
|---------|-------------|---------|
| **Shot Type** | Camera framing | close-up, wide shot, tracking shot |
| **Subject** | Main focus | golden retriever, ocean waves, city skyline |
| **Action** | What's happening | running, crashing, moving through |
| **Setting** | Environment | sunlit meadow, rocky coastline, neon-lit street |
| **Lighting** | Light quality | golden hour, dramatic shadows, soft diffused |
| **Camera Motion** | Movement | slow pan, dolly in, aerial crane shot |
| **Style** | Visual aesthetic | cinematic, anime style, documentary |

### Example Prompts

**Cinematic Nature:**
```
A majestic bald eagle soaring over snow-capped mountains at golden hour, 
dramatic wide shot with slow motion wing movement, shot on IMAX
```

**Product Showcase:**
```
Sleek smartphone rotating slowly on a white marble surface with soft studio 
lighting, highlighting the screen and design details, premium commercial style
```

**Abstract/Artistic:**
```
Ink drops falling into water in slow motion, creating organic flowing patterns, 
macro close-up with vibrant blue and purple colors, ethereal and dreamlike
```

**Action Scene:**
```
A sports car drifting around a corner on a wet city street at night, 
neon reflections on the asphalt, dynamic tracking shot, cinematic
```

---

## 🔧 API Usage (Programmatic)

### Text-to-Video

```python
from foundry_agent import FoundryTemplateAgent

agent = FoundryTemplateAgent()

video_path, status = await agent.generate_video(
    prompt="A cinematic shot of waves crashing on rocks at sunset",
    size="1280x720",      # Landscape
    seconds=8,            # 8 seconds
    output_dir="generated_videos"
)

print(f"Video saved: {video_path}")
print(f"Status: {status}")
```

### Image-to-Video

```python
video_path, status = await agent.generate_video(
    prompt="Gentle wind blowing through the scene, with subtle movement",
    size="1280x720",
    seconds=4,
    output_dir="generated_videos",
    input_reference_path="my_image.jpg"  # Image auto-resized
)
```

### Video Remix

```python
video_path, status = await agent.remix_video(
    video_id="video_69276a126b60819082f97176ea0a3381",
    prompt="Change the lighting to dramatic golden hour with lens flares",
    output_dir="generated_videos"
)
```

---

## 📊 Parameters Reference

### generate_video()

| Parameter | Type | Values | Description |
|-----------|------|--------|-------------|
| `prompt` | str | Any text | Natural language description |
| `size` | str | `1280x720`, `720x1280` | Output resolution |
| `seconds` | int | `4`, `8`, `12` | Video duration |
| `output_dir` | str | Path | Save location |
| `input_reference_path` | str | File path | Reference image (optional) |

### remix_video()

| Parameter | Type | Description |
|-----------|------|-------------|
| `video_id` | str | Full video ID from previous generation |
| `prompt` | str | Modification description |
| `output_dir` | str | Save location |

---

## 📁 Output Files

Generated videos are saved with descriptive filenames:

```
generated_videos/
├── sora_20251126_143022_a1b2c3d4.mp4         # Text-to-video
├── sora_img2vid_20251126_144530_e5f6g7h8.mp4 # Image-to-video  
└── sora_remix_20251126_150045_i9j0k1l2.mp4   # Remix
```

**Filename format:** `sora_[type]_[timestamp]_[short_id].mp4`

The full Video ID is displayed in the generation results and can be used for remix operations.

---

## 🔍 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **401 Unauthorized** | Check Azure credentials and ensure DefaultAzureCredential is configured |
| **400 Bad Request** | Verify prompt isn't empty and parameters are valid |
| **Video generation timeout** | Try a shorter duration or simpler prompt |
| **Image-to-video fails** | Ensure image format is JPEG, PNG, or WEBP |
| **Remix fails** | Use the full Video ID, not the filename |

### Video ID vs Filename

⚠️ **Common mistake:** Using the filename instead of the Video ID for remix operations.

| Type | Format | Example |
|------|--------|---------|
| **Video ID** ✅ | `video_` + 32 hex chars | `video_69276a126b60819082f97176ea0a3381` |
| **Filename** ❌ | `sora_..._[8 chars].mp4` | `sora_remix_20251126_143022_f66d5bdc.mp4` |

The **Video ID** is shown in the generation results. Copy this value for remix operations.

### Rate Limiting

If you encounter rate limit errors:
1. Check your Azure OpenAI quota (minimum 20,000 TPM recommended)
2. Wait between generation requests
3. Use shorter video durations

---

## 🛠️ Agent Configuration

### Skills Defined

| Skill | Description |
|-------|-------------|
| `video_generation` | Text-to-video generation |
| `video_from_image` | Image-to-video transformation |
| `video_to_video` | Video style transfer (organization-gated) |
| `video_remix` | Modify existing videos |
| `video_prompt_assistance` | Help crafting effective prompts |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Yes | - | Azure AI Foundry project URL |
| `AZURE_OPENAI_ENDPOINT` | No | Auto-derived | Azure OpenAI endpoint for Sora 2 |
| `A2A_PORT` | No | `9020` | A2A server port |
| `A2A_ENDPOINT` | No | `localhost` | A2A server host |
| `HOST_AGENT_URL` | No | - | Host agent URL for auto-registration |

---

## 📚 Additional Resources

- [Azure OpenAI Sora 2 Documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [A2A Protocol Specification](https://github.com/microsoft/a2a)
- [Main Project README](../../README.md)

---

## ⚠️ Known Limitations

- **Video-to-Video:** Currently organization-gated by OpenAI
- **Maximum Duration:** 12 seconds per generation
- **Processing Time:** 1-5 minutes depending on duration and complexity
- **Remix Availability:** Only works with videos generated in the same Azure Foundry resource


## TODO
- **Intergetion with backend** Currently this is only supported in the azurefoundry_video directory without broader integratedd support

---

**Happy Video Generating! 🎬✨**
