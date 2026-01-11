import asyncio
import logging
import os
import traceback
from collections.abc import AsyncIterator
from typing import List
import threading

import click
import gradio as gr
import uvicorn

from foundry_agent_executor import create_foundry_agent_executor, initialize_foundry_template_agents_at_startup
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill

load_dotenv()

# Configure logging - hide verbose Azure SDK logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Silence verbose Azure SDK HTTP logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)


def _normalize_env_value(raw_value: str | None) -> str:
    if raw_value is None:
        return ''
    return raw_value.strip()


def _resolve_default_host() -> str:
    value = _normalize_env_value(os.getenv('A2A_ENDPOINT'))
    return value or 'localhost'


def _resolve_default_port() -> int:
    raw_port = _normalize_env_value(os.getenv('A2A_PORT'))
    if raw_port:
        try:
            return int(raw_port)
        except ValueError:
            logger.warning("Invalid A2A_PORT value '%s'; defaulting to 9020", raw_port)
    return 9020


def resolve_agent_url(bind_host: str, bind_port: int) -> str:
    endpoint = _normalize_env_value(os.getenv('A2A_ENDPOINT'))
    if endpoint:
        if endpoint.startswith(('http://', 'https://')):
            return endpoint.rstrip('/') + '/'
        host_for_url = endpoint
    else:
        host_for_url = bind_host if bind_host != "0.0.0.0" else _resolve_default_host()

    return f"http://{host_for_url}:{bind_port}/"

# Import self-registration utility
try:
    from utils.self_registration import register_with_host_agent, get_host_agent_url
    SELF_REGISTRATION_AVAILABLE = True
    logger.info("✅ Self-registration utility loaded")
except ImportError:
    # Fallback if utils not available
    async def register_with_host_agent(agent_card, host_url=None):
        logger.info("ℹ️ Self-registration utility not available - skipping registration")
        return False
    def get_host_agent_url() -> str:
        return ""
    SELF_REGISTRATION_AVAILABLE = False

# ⚠️ CUSTOMIZATION: Update these default ports to avoid conflicts with other agents
DEFAULT_HOST = _resolve_default_host()
DEFAULT_PORT = _resolve_default_port()  # Default: 9020 (set in A2A_PORT env var)
DEFAULT_UI_PORT = 9120  # Default UI port for Gradio interface

HOST_AGENT_URL = _normalize_env_value(get_host_agent_url())

# Global reference to the agent executor to check for pending tasks
agent_executor_instance = None


def _build_agent_skills() -> List[AgentSkill]:
    """
    Define the video generation agent's skills/capabilities.
    These appear in the agent catalog and help users understand what the agent can do.
    """
    return [
        AgentSkill(
            id='video_generation',
            name='AI Video Generation',
            description="Generate high-quality AI videos from text prompts using Azure OpenAI's Sora 2 model. Create cinematic scenes, animations, and visual content with natural language descriptions.",
            tags=['video', 'sora', 'generation', 'ai', 'creative', 'multimedia'],
            examples=[
                'Generate a video of a golden retriever running through a sunlit meadow at sunset',
                'Create a cinematic shot of waves crashing on a rocky coastline at dawn',
                'Make a video of a futuristic city with flying cars at night',
            ],
        ),
        AgentSkill(
            id='video_from_image',
            name='Image-to-Video Generation',
            description="Transform static images into dynamic videos. Provide a reference image and describe the motion or animation you want to create.",
            tags=['video', 'image', 'animation', 'transform', 'sora'],
            examples=[
                'Animate this landscape image with gentle wind blowing through the trees',
                'Turn this portrait into a video where the person slowly smiles',
                'Make the water in this photo start flowing naturally',
            ],
        ),
        AgentSkill(
            id='video_to_video',
            name='Video-to-Video Generation',
            description="Transform existing videos using AI. Upload a reference video and describe the transformation you want - change styles, atmospheres, or subjects while maintaining motion and structure.",
            tags=['video', 'transform', 'sora', 'style-transfer', 'reference'],
            examples=[
                'Transform this daytime scene into a moonlit nighttime video',
                'Convert this video into an animated cartoon style',
                'Change this urban scene to a post-apocalyptic landscape',
            ],
        ),
        AgentSkill(
            id='video_remix',
            name='Video Remix',
            description="Modify specific aspects of previously generated Sora 2 videos while preserving core elements like scene transitions and visual layout. Make targeted adjustments to color palettes, lighting, or style.",
            tags=['video', 'remix', 'edit', 'modify', 'sora'],
            examples=[
                'Shift the color palette to warm sunset tones',
                'Change the lighting to dramatic noir style',
                'Transform the season from summer to winter',
            ],
        ),
        AgentSkill(
            id='video_prompt_assistance',
            name='Video Prompt Crafting',
            description="Help craft effective prompts for video generation. Get advice on describing scenes, camera movements, lighting, and style for optimal results.",
            tags=['prompt', 'assistance', 'help', 'creative', 'writing'],
            examples=[
                'How do I describe a tracking shot in my video prompt?',
                'What details should I include for a cinematic video?',
                'Help me write a prompt for a product showcase video',
            ],
        ),
    ]


def _create_agent_card(host: str, port: int) -> AgentCard:
    """
    Define the Sora 2 Video Generation agent's identity.
    This is used throughout the application for discovery and routing.
    """
    skills = _build_agent_skills()
    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST
    
    return AgentCard(
        name='Sora 2 Video Generator',
        description="Generate stunning AI videos from text prompts using Azure OpenAI's Sora 2 model. Create cinematic scenes, product demos, animations, and creative visual content with natural language descriptions. Supports 4-12 second videos in landscape or portrait format.",
        url=resolve_agent_url(resolved_host_for_url, port),
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text', 'video'],
        capabilities={"streaming": True, "video_generation": True},
        skills=skills,
    )


def create_a2a_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Create A2A server application for your custom agent."""
    global agent_executor_instance

    # Get agent card (defined once in _create_agent_card function)
    agent_card = _create_agent_card(host, port)

    agent_executor_instance = create_foundry_agent_executor(agent_card)

    # Create request handler
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor_instance, 
        task_store=InMemoryTaskStore()
    )

    # Create A2A application
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, 
        http_handler=request_handler
    )
    
    # Get routes
    routes = a2a_app.routes()
    
    # Add health check endpoint
    async def health_check(_: Request) -> PlainTextResponse:
        return PlainTextResponse('Sora 2 Video Generator is running!')
    
    routes.append(
        Route(
            path='/health',
            methods=['GET'],
            endpoint=health_check
        )
    )

    # Create Starlette app
    app = Starlette(routes=routes)
    
    return app


def run_a2a_server_in_thread(host: str, port: int):
    """Run A2A server in a separate thread."""
    print(f"Starting Sora 2 Video Generator A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


async def register_agent_with_host(agent_card):
    """Register this agent with the host agent after startup."""
    if SELF_REGISTRATION_AVAILABLE:
        # Wait a moment for server to fully start
        await asyncio.sleep(2)
        try:
            if not HOST_AGENT_URL:
                logger.info("ℹ️ Host agent URL not configured; skipping registration attempt.")
                return

            logger.info(f"🤝 Attempting to register '{agent_card.name}' with host agent at {HOST_AGENT_URL}...")
            registration_success = await register_with_host_agent(agent_card, host_url=HOST_AGENT_URL)
            if registration_success:
                logger.info(f"🎉 '{agent_card.name}' successfully registered with host agent!")
            else:
                logger.info(f"📡 '{agent_card.name}' registration failed - host agent may be unavailable")
        except Exception as e:
            logger.warning(f"⚠️ Registration attempt failed: {e}")


def start_background_registration(agent_card):
    """Start background registration task."""
    if SELF_REGISTRATION_AVAILABLE:
        def run_registration():
            asyncio.run(register_agent_with_host(agent_card))
        
        registration_thread = threading.Thread(target=run_registration, daemon=True)
        registration_thread.start()
        logger.info(f"🚀 '{agent_card.name}' starting with background registration enabled")
    else:
        logger.info(f"📡 '{agent_card.name}' starting without self-registration")


async def get_foundry_response(
    message: str,
    _history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    """Get response from the Azure Foundry agent for the Gradio UI."""
    global agent_executor_instance
    try:
        # Use the same shared agent instance as the A2A executor
        if agent_executor_instance is None:
            # Initialize the executor if not already done
            agent_executor_instance = create_foundry_agent_executor(
                AgentCard(name="UI Agent", description="UI Agent", url="", version="1.0.0")
            )
        
        # Get the shared agent from the executor
        foundry_agent = await agent_executor_instance._get_or_create_agent()
        
        # Use the same shared thread as the A2A executor to minimize API calls
        thread_id = await agent_executor_instance._get_or_create_thread("ui_context", foundry_agent)
        
        # Send a status update (⚠️ CUSTOMIZATION: Update this message)
        yield gr.ChatMessage(
            role="assistant",
            content="🤔 **Processing your request...**",
        )
        
        # Run the conversation using the streaming method
        response_count = 0
        async for response in foundry_agent.run_conversation_stream(thread_id, message):
            print("[DEBUG] get_foundry_response: response=", response)
            if isinstance(response, str):
                if response.strip():
                    # Filter out processing messages
                    if not any(phrase in response.lower() for phrase in [
                        "processing your request", "🤖 processing", "processing...",
                        "🤔 processing"
                    ]):
                        yield gr.ChatMessage(role="assistant", content=response)
                        response_count += 1
            else:
                # handle other types if needed
                logger.debug(f"get_foundry_response: Unexpected response type: {type(response)}")
                yield gr.ChatMessage(
                    role="assistant",
                    content=f"An error occurred while processing your request: {str(response)}. Please check the server logs for details.",
                )
                response_count += 1
        
        # If no responses were yielded, show a default message
        if response_count == 0:
            yield gr.ChatMessage(
                role="assistant",
                content="I processed your request but didn't generate a response. Please try rephrasing your question or providing more context."
            )
            
    except Exception as e:
        logger.error(f"Error in get_foundry_response (Type: {type(e)}): {e}")
        traceback.print_exc()
        yield gr.ChatMessage(
            role="assistant",
            content=f"An error occurred while processing your request: {str(e)}. Please check the server logs for details.",
        )


async def launch_ui(host: str = "0.0.0.0", ui_port: int = DEFAULT_UI_PORT, a2a_port: int = DEFAULT_PORT):
    """Launch Gradio UI and A2A server simultaneously for the Sora 2 Video Generator."""
    print("Starting Sora 2 Video Generator with both UI and A2A server...")
    
    # Verify required environment variables
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Initialize agent at startup BEFORE starting servers
    print("🚀 Initializing Sora 2 Video Generator at startup...")
    try:
        await initialize_foundry_template_agents_at_startup()
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agent at startup: {e}")
        raise

    # Start A2A server in a separate thread
    a2a_thread = threading.Thread(
        target=run_a2a_server_in_thread,
        args=(host if host != "0.0.0.0" else DEFAULT_HOST, a2a_port),
        daemon=True
    )
    a2a_thread.start()
    
    # Give the A2A server a moment to start
    await asyncio.sleep(2)
    
    # Get agent card and start background registration
    agent_card = _create_agent_card(host, a2a_port)
    start_background_registration(agent_card)

    resolved_host_for_url = host if host != "0.0.0.0" else DEFAULT_HOST
    display_host = resolved_host_for_url
    ui_display_url = f"http://{display_host}:{ui_port}"
    a2a_display_url = resolve_agent_url(display_host, a2a_port).rstrip('/')

    # Get the directory where this script is located for proper static file paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(script_dir, "static", "a2a.png")
    
    # Store for tracking the last generated video ID for remix
    last_video_id_store = {"video_id": None}
    
    with gr.Blocks(theme=gr.themes.Ocean(), title="Sora 2 Video Generator") as demo:
        # Header
        with gr.Row():
            with gr.Column(scale=1):
                if os.path.exists(logo_path):
                    gr.Image(
                        logo_path,
                        width=80,
                        height=80,
                        scale=0,
                        show_label=False,
                        show_download_button=False,
                        container=False,
                        show_fullscreen_button=False,
                    )
            with gr.Column(scale=10):
                gr.Markdown(f"""
                ## 🎬 Sora 2 Video Generator
                **UI:** {ui_display_url} | **A2A API:** {a2a_display_url}
                """)
        
        # Main layout: Chat on left, Controls on right
        with gr.Row():
            # Left side: Chat interface
            with gr.Column(scale=3):
                # Chat history display
                chatbot = gr.Chatbot(
                    label="Video Generation Chat",
                    height=500,
                    type="messages",
                    show_copy_button=True,
                    avatar_images=(None, logo_path if os.path.exists(logo_path) else None),
                )
                
                # Input area with image upload
                with gr.Row():
                    with gr.Column(scale=4):
                        user_input = gr.Textbox(
                            label="",
                            placeholder="Describe your video... (drag & drop an image for image-to-video, or enter a video ID to remix)",
                            lines=2,
                            show_label=False,
                        )
                    with gr.Column(scale=1):
                        image_input = gr.Image(
                            label="Reference Image",
                            type="filepath",
                            sources=["upload", "clipboard"],
                            height=80,
                            show_label=True,
                        )
                
                with gr.Row():
                    submit_btn = gr.Button("🎬 Generate", variant="primary", scale=2)
                    clear_btn = gr.Button("🗑️ Clear", scale=1)
                
                # Last Video ID display for easy remix
                last_video_display = gr.Markdown(
                    value="*No video generated yet*",
                    label="Last Video ID"
                )
            
            # Right side: Controls and settings
            with gr.Column(scale=1):
                gr.Markdown("### ⚙️ Video Settings")
                
                # Generation mode selector
                mode_selector = gr.Radio(
                    choices=["Auto-detect", "Text-to-Video", "Image-to-Video", "Remix"],
                    value="Auto-detect",
                    label="Generation Mode",
                    info="Auto-detect chooses based on your input"
                )
                
                # Video parameters
                video_size = gr.Dropdown(
                    choices=["1280x720", "720x1280"],
                    value="1280x720",
                    label="📐 Resolution",
                    info="Landscape or Portrait"
                )
                
                video_duration = gr.Dropdown(
                    choices=["4", "8", "12"],
                    value="8",
                    label="⏱️ Duration (seconds)",
                )
                
                gr.Markdown("---")
                gr.Markdown("### 🔄 Remix Settings")
                
                remix_video_id = gr.Textbox(
                    label="Video ID (for Remix)",
                    placeholder="video_abc123...",
                    info="Paste a video ID to remix it"
                )
                
                use_last_video_btn = gr.Button("📋 Use Last Generated Video", size="sm")
                
                gr.Markdown("---")
                gr.Markdown("""
                ### 💡 Quick Tips
                
                **Text-to-Video:**
                - Describe scene, action, lighting
                - Include camera movements
                
                **Image-to-Video:**
                - Drag image to the upload area
                - Describe the motion/animation
                
                **Remix:**
                - Paste Video ID in the box
                - Describe ONE specific change
                """)
        
        # State for chat history
        chat_history = gr.State([])
        
        async def process_video_request(
            message: str,
            image: str | None,
            history: list,
            mode: str,
            size: str,
            duration: str,
            remix_id: str
        ):
            """Process video generation request in chat format."""
            if not message or not message.strip():
                yield history, "*Please enter a prompt*", last_video_id_store.get("video_id", "")
                return
            
            # Add user message to history
            user_msg = {"role": "user", "content": message}
            if image:
                user_msg["content"] = f"[Image attached]\n\n{message}"
            history = history + [user_msg]
            
            # Determine generation mode
            actual_mode = mode
            
            # Check if user included a video ID in the message for remix
            import re
            video_id_in_message = re.search(r'(video_[a-f0-9]{32})', message)
            
            if mode == "Auto-detect":
                if video_id_in_message:
                    actual_mode = "Remix"
                    # Extract the video ID and use it
                    remix_id = video_id_in_message.group(1)
                elif remix_id and remix_id.strip().startswith("video_"):
                    actual_mode = "Remix"
                elif image:
                    actual_mode = "Image-to-Video"
                else:
                    actual_mode = "Text-to-Video"
            
            # If remix mode but video ID was in message, use that
            if actual_mode == "Remix" and video_id_in_message and not remix_id:
                remix_id = video_id_in_message.group(1)
            
            # Initial response
            thinking_msg = {"role": "assistant", "content": f"🎬 **Generating {actual_mode}...**\n\nThis may take 1-3 minutes."}
            history = history + [thinking_msg]
            yield history, f"*Generating {actual_mode}...*", remix_id
            
            try:
                foundry_agent = await agent_executor_instance._get_or_create_agent()
                video_path = None
                status_message = ""
                new_video_id = None
                
                if actual_mode == "Remix":
                    vid_id = remix_id.strip() if remix_id else ""
                    
                    # Validate video ID format
                    if not vid_id:
                        history[-1] = {"role": "assistant", "content": "❌ Please enter a Video ID in the Remix Settings panel, or include it in your message.\n\n**Example:** `video_abc123...` followed by your remix prompt"}
                        yield history, "*Error: No video ID*", ""
                        return
                    
                    if not vid_id.startswith("video_") or len(vid_id) < 38:
                        history[-1] = {"role": "assistant", "content": f"❌ Invalid Video ID format: `{vid_id}`\n\n**Expected format:** `video_` followed by 32 hex characters\n**Example:** `video_69276a126b60819082f97176ea0a3381`\n\n*Note: The filename (like `sora_remix_...mp4`) is NOT the video ID. Use the full video ID shown in the generation results.*"}
                        yield history, "*Error: Invalid video ID format*", ""
                        return
                    
                    # Remove video ID from prompt if it was in the message
                    clean_prompt = message.strip()
                    if video_id_in_message:
                        clean_prompt = re.sub(r'video_[a-f0-9]{32}', '', clean_prompt).strip()
                        clean_prompt = re.sub(r'^[:\-\s]+', '', clean_prompt).strip()  # Remove leading punctuation
                    
                    if not clean_prompt:
                        clean_prompt = message.strip()  # Fall back to original if cleaning removed everything
                    
                    logger.info(f"Remix request - Video ID: {vid_id}, Prompt: {clean_prompt}")
                    
                    video_path, status_message = await foundry_agent.remix_video(
                        video_id=vid_id,
                        prompt=clean_prompt,
                        output_dir="generated_videos"
                    )
                    # Extract new video ID from status message
                    if "New Remix Video ID" in status_message:
                        import re
                        match = re.search(r'`(video_[a-f0-9]+)`', status_message)
                        if match:
                            new_video_id = match.group(1)
                    
                elif actual_mode == "Image-to-Video":
                    if not image:
                        history[-1] = {"role": "assistant", "content": "❌ Please upload an image for Image-to-Video generation."}
                        yield history, "*Error: No image*", ""
                        return
                    
                    video_path, status_message = await foundry_agent.generate_video(
                        prompt=message.strip(),
                        size=size,
                        seconds=int(duration),
                        output_dir="generated_videos",
                        input_reference_path=image
                    )
                    # Extract video ID
                    if "Video ID" in status_message:
                        import re
                        match = re.search(r'`(video_[a-f0-9]+)`', status_message)
                        if match:
                            new_video_id = match.group(1)
                    
                else:  # Text-to-Video
                    video_path, status_message = await foundry_agent.generate_video(
                        prompt=message.strip(),
                        size=size,
                        seconds=int(duration),
                        output_dir="generated_videos"
                    )
                    # Extract video ID
                    if "Video ID" in status_message:
                        import re
                        match = re.search(r'`(video_[a-f0-9]+)`', status_message)
                        if match:
                            new_video_id = match.group(1)
                
                # Update the video ID store
                if new_video_id:
                    last_video_id_store["video_id"] = new_video_id
                
                # Build response with video
                if video_path and os.path.exists(video_path):
                    # Create response with video
                    response_content = f"{status_message}\n\n"
                    history[-1] = {
                        "role": "assistant", 
                        "content": gr.Video(value=video_path)
                    }
                    # Add status as separate message
                    history.append({"role": "assistant", "content": status_message})
                    
                    last_vid_display = f"**Last Video ID:** `{new_video_id}`" if new_video_id else "*No video ID available*"
                    yield history, last_vid_display, new_video_id or ""
                else:
                    history[-1] = {"role": "assistant", "content": status_message}
                    yield history, "*Generation failed*", ""
                    
            except Exception as e:
                logger.error(f"Error in video generation: {e}")
                import traceback
                traceback.print_exc()
                history[-1] = {"role": "assistant", "content": f"❌ **Error:** {str(e)}"}
                yield history, "*Error occurred*", ""
        
        def clear_chat():
            """Clear chat history."""
            return [], None, "", "*No video generated yet*", ""
        
        def use_last_video(current_id):
            """Copy last video ID to remix field."""
            vid = last_video_id_store.get("video_id", "")
            return vid if vid else current_id
        
        # Event handlers
        submit_btn.click(
            fn=process_video_request,
            inputs=[user_input, image_input, chat_history, mode_selector, video_size, video_duration, remix_video_id],
            outputs=[chatbot, last_video_display, remix_video_id],
        ).then(
            fn=lambda: ("", None),
            outputs=[user_input, image_input]
        ).then(
            fn=lambda h: h,
            inputs=[chatbot],
            outputs=[chat_history]
        )
        
        # Also submit on Enter key
        user_input.submit(
            fn=process_video_request,
            inputs=[user_input, image_input, chat_history, mode_selector, video_size, video_duration, remix_video_id],
            outputs=[chatbot, last_video_display, remix_video_id],
        ).then(
            fn=lambda: ("", None),
            outputs=[user_input, image_input]
        ).then(
            fn=lambda h: h,
            inputs=[chatbot],
            outputs=[chat_history]
        )
        
        clear_btn.click(
            fn=clear_chat,
            outputs=[chatbot, image_input, user_input, last_video_display, remix_video_id]
        ).then(
            fn=lambda: [],
            outputs=[chat_history]
        )
        
        use_last_video_btn.click(
            fn=use_last_video,
            inputs=[remix_video_id],
            outputs=[remix_video_id]
        )

    print(f"Launching Sora 2 Video Generator Gradio interface on {host}:{ui_port}...")
    demo.queue().launch(
        server_name=host,
        server_port=ui_port,
    )
    print("Sora 2 Video Generator Gradio application has been shut down.")


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Launch A2A server mode for the Sora 2 Video Generator with startup initialization."""
    # Verify required environment variables
    required_env_vars = [
        'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT',
        'AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Initialize agent at startup BEFORE starting server
    print("🚀 Initializing Sora 2 Video Generator at startup...")
    try:
        asyncio.run(initialize_foundry_template_agents_at_startup())
        print("✅ Agent initialization completed successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize agent at startup: {e}")
        raise

    print(f"Starting Sora 2 Video Generator A2A server on {host}:{port}...")
    app = create_a2a_server(host, port)
    
    # Get agent card and start background registration
    agent_card = _create_agent_card(host, port)
    start_background_registration(agent_card)
    
    uvicorn.run(app, host=host, port=port)


@click.command()
@click.option('--host', 'host', default=DEFAULT_HOST, help='Host to bind to')
@click.option('--port', 'port', default=DEFAULT_PORT, help='Port for A2A server')
@click.option('--ui', is_flag=True, help='Launch Gradio UI (also runs A2A server)')
@click.option('--ui-port', 'ui_port', default=DEFAULT_UI_PORT, help='Port for Gradio UI (only used with --ui flag)')
def cli(host: str, port: int, ui: bool, ui_port: int):
    """
    Sora 2 Video Generator - Generate AI videos from text prompts.
    
    Run as an A2A server or with Gradio UI + A2A server.
    Uses Azure OpenAI's Sora 2 model for video generation.
    """
    if ui:
        asyncio.run(launch_ui(host, ui_port, port))
    else:
        main(host, port)


if __name__ == '__main__':
    cli()
