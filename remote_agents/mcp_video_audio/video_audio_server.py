#!/usr/bin/env python
"""
MCP Server for Video and Audio editing using FFmpeg.
Adapted from https://github.com/misbahsy/video-audio-mcp
with HTTP transport support for Azure Container Apps deployment.
"""
import os
import re
import argparse
import tempfile
import shutil
import subprocess
from typing import Dict

import ffmpeg
from mcp.server.fastmcp import FastMCP

# Initialize the FastMCP server
app = FastMCP(name="video-audio-mcp-server")

# Download directory for serving processed files
DOWNLOAD_DIR = "/tmp/video_audio_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ---- File Download Tool ----

@app.tool()
def download_file(file_path: str, filename: str = None) -> Dict:
    """
    Makes a processed video/audio file available for download.
    Copies the file to the download directory and returns a download URL.

    Args:
        file_path: Path to the processed file to make available for download.
        filename: Optional filename for the download. If not provided, uses the original filename.

    Returns:
        Dictionary with download_url and filename.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    if filename is None:
        filename = os.path.basename(file_path)

    # Sanitize filename
    safe_filename = os.path.basename(filename)
    dest_path = os.path.join(DOWNLOAD_DIR, safe_filename)

    try:
        shutil.copy2(file_path, dest_path)
        return {
            "download_url": f"/download/{safe_filename}",
            "filename": safe_filename,
            "file_size": os.path.getsize(dest_path),
        }
    except Exception as e:
        return {"error": f"Failed to prepare file for download: {str(e)}"}


# ---- Test Media Generation ----

@app.tool()
def generate_test_media(
    output_path: str,
    media_type: str = "video",
    duration: int = 5,
) -> str:
    """
    Generates a synthetic test video or audio file using FFmpeg's built-in sources.
    Useful for testing without needing to upload files.

    Args:
        output_path: Path to save the generated test file.
        media_type: Type of media to generate - 'video' (with audio) or 'audio'.
        duration: Duration in seconds (default 5).

    Returns:
        Success message with file path, or error message.
    """
    try:
        if media_type == "video":
            subprocess.run(
                [
                    "ffmpeg",
                    "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=640x480:rate=30",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                    "-c:v", "libx264", "-c:a", "aac",
                    "-y", output_path,
                ],
                check=True, capture_output=True,
            )
        elif media_type == "audio":
            subprocess.run(
                [
                    "ffmpeg",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                    "-c:a", "libmp3lame",
                    "-y", output_path,
                ],
                check=True, capture_output=True,
            )
        else:
            return f"Error: Invalid media_type '{media_type}'. Must be 'video' or 'audio'."

        file_size = os.path.getsize(output_path)
        return f"Test {media_type} generated successfully at {output_path} ({file_size} bytes)"
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error generating test media: {stderr}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


# ---- Health Check ----

@app.tool()
def health_check() -> str:
    """Returns a simple health status to confirm the server is running."""
    return "Server is healthy!"


# ---- Video Tools ----

@app.tool()
def extract_audio_from_video(
    video_path: str, output_audio_path: str, audio_codec: str = "mp3"
) -> str:
    """Extracts audio from a video file and saves it."""
    try:
        input_stream = ffmpeg.input(video_path)
        output_stream = input_stream.output(output_audio_path, acodec=audio_codec)
        output_stream.run(capture_stdout=True, capture_stderr=True)
        return f"Audio extracted successfully to {output_audio_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error extracting audio: {error_message}"
    except FileNotFoundError:
        return f"Error: Input video file not found at {video_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def add_audio_to_video(
    video_path: str,
    audio_path: str,
    output_video_path: str,
    mode: str = "replace",
    audio_volume: float = 1.0,
) -> str:
    """
    Adds an audio track to a video file. Use this to combine a separate audio
    file (e.g. background music, voiceover) with a video.

    Args:
        video_path: Path to the input video file.
        audio_path: Path to the audio file to add (mp3, wav, aac, etc.).
        output_video_path: Path for the output video with audio.
        mode: 'replace' replaces any existing audio with the new audio.
              'mix' mixes the new audio with the video's existing audio track.
        audio_volume: Volume multiplier for the added audio (1.0 = original, 0.5 = half).

    Returns:
        Success message with output path, or error description.
    """
    # Skip existence check for URLs (FFmpeg reads URLs directly)
    if not video_path.startswith(("http://", "https://")) and not os.path.exists(video_path):
        return f"Error: Video file not found at {video_path}"
    if not audio_path.startswith(("http://", "https://")) and not os.path.exists(audio_path):
        return f"Error: Audio file not found at {audio_path}"

    try:
        video_in = ffmpeg.input(video_path)
        audio_in = ffmpeg.input(audio_path)

        if audio_volume != 1.0:
            audio_in = audio_in.filter("volume", audio_volume)

        if mode == "mix":
            # Mix the new audio with the video's existing audio
            try:
                mixed = ffmpeg.filter([video_in.audio, audio_in], "amix",
                                      inputs=2, duration="shortest")
                out = ffmpeg.output(video_in.video, mixed, output_video_path,
                                    vcodec="copy", acodec="aac")
                out.run(capture_stdout=True, capture_stderr=True)
                return f"Audio mixed with video successfully, saved to {output_video_path}"
            except ffmpeg.Error:
                # Video may have no audio track — fall through to replace mode
                pass

        # Replace mode (or mix fallback): map video stream + new audio stream
        try:
            out = ffmpeg.output(video_in.video, audio_in, output_video_path,
                                vcodec="copy", acodec="aac", shortest=None)
            out.run(capture_stdout=True, capture_stderr=True)
            return f"Audio added to video successfully (replace), saved to {output_video_path}"
        except ffmpeg.Error as e:
            # Fallback: re-encode everything
            error_msg_copy = e.stderr.decode("utf8") if e.stderr else str(e)
            try:
                out = ffmpeg.output(video_in.video, audio_in, output_video_path,
                                    acodec="aac", shortest=None)
                out.run(capture_stdout=True, capture_stderr=True)
                return f"Audio added to video successfully (re-encoded), saved to {output_video_path}"
            except ffmpeg.Error as e2:
                error_msg_recode = e2.stderr.decode("utf8") if e2.stderr else str(e2)
                return f"Error adding audio. Copy attempt: {error_msg_copy}. Re-encode attempt: {error_msg_recode}"

    except FileNotFoundError:
        return "Error: ffmpeg not found. Make sure FFmpeg is installed."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def trim_video(
    video_path: str, output_video_path: str, start_time: str, end_time: str
) -> str:
    """Trims a video to the specified start and end times."""
    try:
        input_stream = ffmpeg.input(video_path, ss=start_time, to=end_time)
        output_stream = input_stream.output(output_video_path, c="copy")
        output_stream.run(capture_stdout=True, capture_stderr=True)
        return f"Video trimmed successfully (codec copy) to {output_video_path}"
    except ffmpeg.Error as e:
        error_message_copy = e.stderr.decode("utf8") if e.stderr else str(e)
        try:
            input_stream_recode = ffmpeg.input(
                video_path, ss=start_time, to=end_time
            )
            output_stream_recode = input_stream_recode.output(output_video_path)
            output_stream_recode.run(capture_stdout=True, capture_stderr=True)
            return f"Video trimmed successfully (re-encoded) to {output_video_path}"
        except ffmpeg.Error as e_recode:
            error_message_recode = (
                e_recode.stderr.decode("utf8") if e_recode.stderr else str(e_recode)
            )
            return f"Error trimming video. Copy attempt: {error_message_copy}. Re-encode attempt: {error_message_recode}"
    except FileNotFoundError:
        return f"Error: Input video file not found at {video_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def convert_video_format(
    input_video_path: str, output_video_path: str, target_format: str
) -> str:
    """Converts a video file to the specified target format."""
    primary_kwargs = {"format": target_format, "vcodec": "copy", "acodec": "copy"}
    fallback_kwargs = {"format": target_format}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def convert_video_properties(
    input_video_path: str,
    output_video_path: str,
    target_format: str,
    resolution: str = None,
    video_codec: str = None,
    video_bitrate: str = None,
    frame_rate: int = None,
    audio_codec: str = None,
    audio_bitrate: str = None,
    audio_sample_rate: int = None,
    audio_channels: int = None,
) -> str:
    """Converts video file format and properties."""
    try:
        stream = ffmpeg.input(input_video_path)
        kwargs = {}
        vf_filters = []
        if resolution and resolution.lower() != "preserve":
            if "x" in resolution:
                vf_filters.append(f"scale={resolution}")
            else:
                vf_filters.append(f"scale=-2:{resolution}")
        if vf_filters:
            kwargs["vf"] = ",".join(vf_filters)
        if video_codec:
            kwargs["vcodec"] = video_codec
        if video_bitrate:
            kwargs["video_bitrate"] = video_bitrate
        if frame_rate:
            kwargs["r"] = frame_rate
        if audio_codec:
            kwargs["acodec"] = audio_codec
        if audio_bitrate:
            kwargs["audio_bitrate"] = audio_bitrate
        if audio_sample_rate:
            kwargs["ar"] = audio_sample_rate
        if audio_channels:
            kwargs["ac"] = audio_channels
        kwargs["format"] = target_format
        output_stream = stream.output(output_video_path, **kwargs)
        output_stream.run(capture_stdout=True, capture_stderr=True)
        return f"Video converted successfully to {output_video_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error converting video properties: {error_message}"
    except FileNotFoundError:
        return f"Error: Input video file not found at {input_video_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def change_aspect_ratio(
    video_path: str,
    output_video_path: str,
    target_aspect_ratio: str,
    resize_mode: str = "pad",
    padding_color: str = "black",
) -> str:
    """Changes the aspect ratio of a video using padding or cropping."""
    try:
        probe = ffmpeg.probe(video_path)
        video_stream_info = next(
            (
                stream
                for stream in probe["streams"]
                if stream["codec_type"] == "video"
            ),
            None,
        )
        if not video_stream_info:
            return "Error: No video stream found in the input file."
        original_width = int(video_stream_info["width"])
        original_height = int(video_stream_info["height"])
        num, den = map(int, target_aspect_ratio.split(":"))
        target_ar_val = num / den
        original_ar_val = original_width / original_height

        if resize_mode == "pad":
            if abs(original_ar_val - target_ar_val) < 1e-4:
                try:
                    ffmpeg.input(video_path).output(
                        output_video_path, c="copy"
                    ).run(capture_stdout=True, capture_stderr=True)
                    return f"Video aspect ratio already matches. Copied to {output_video_path}."
                except ffmpeg.Error:
                    ffmpeg.input(video_path).output(output_video_path).run(
                        capture_stdout=True, capture_stderr=True
                    )
                    return f"Video aspect ratio already matches. Re-encoded to {output_video_path}."
            if original_ar_val > target_ar_val:
                final_w = int(original_height * target_ar_val)
                final_h = original_height
            else:
                final_w = original_width
                final_h = int(original_width / target_ar_val)
            vf_filter = f"scale={final_w}:{final_h}:force_original_aspect_ratio=decrease,pad={final_w}:{final_h}:(ow-iw)/2:(oh-ih)/2:{padding_color}"
        elif resize_mode == "crop":
            if abs(original_ar_val - target_ar_val) < 1e-4:
                try:
                    ffmpeg.input(video_path).output(
                        output_video_path, c="copy"
                    ).run(capture_stdout=True, capture_stderr=True)
                    return f"Video aspect ratio already matches. Copied to {output_video_path}."
                except ffmpeg.Error:
                    ffmpeg.input(video_path).output(output_video_path).run(
                        capture_stdout=True, capture_stderr=True
                    )
                    return f"Video aspect ratio already matches. Re-encoded to {output_video_path}."
            if original_ar_val > target_ar_val:
                new_width = int(original_height * target_ar_val)
                vf_filter = (
                    f"crop={new_width}:{original_height}:(iw-{new_width})/2:0"
                )
            else:
                new_height = int(original_width / target_ar_val)
                vf_filter = (
                    f"crop={original_width}:{new_height}:0:(ih-{new_height})/2"
                )
        else:
            return f"Error: Invalid resize_mode '{resize_mode}'. Must be 'pad' or 'crop'."

        try:
            ffmpeg.input(video_path).output(
                output_video_path, vf=vf_filter, acodec="copy"
            ).run(capture_stdout=True, capture_stderr=True)
            return f"Video aspect ratio changed (audio copy) to {target_aspect_ratio} using {resize_mode}. Saved to {output_video_path}"
        except ffmpeg.Error as e_acopy:
            try:
                ffmpeg.input(video_path).output(
                    output_video_path, vf=vf_filter
                ).run(capture_stdout=True, capture_stderr=True)
                return f"Video aspect ratio changed (audio re-encoded) to {target_aspect_ratio} using {resize_mode}. Saved to {output_video_path}"
            except ffmpeg.Error as e_recode_all:
                err_acopy_msg = (
                    e_acopy.stderr.decode("utf8") if e_acopy.stderr else str(e_acopy)
                )
                err_recode_msg = (
                    e_recode_all.stderr.decode("utf8")
                    if e_recode_all.stderr
                    else str(e_recode_all)
                )
                return f"Error changing aspect ratio. Audio copy attempt failed: {err_acopy_msg}. Full re-encode attempt also failed: {err_recode_msg}."
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error changing aspect ratio: {error_message}"
    except FileNotFoundError:
        return f"Error: Input video file not found at {video_path}"
    except ValueError:
        return "Error: Invalid target_aspect_ratio format. Expected 'num:den' (e.g., '16:9')."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def set_video_resolution(
    input_video_path: str, output_video_path: str, resolution: str
) -> str:
    """Sets the resolution of a video."""
    vf_filters = []
    if "x" in resolution:
        vf_filters.append(f"scale={resolution}")
    else:
        vf_filters.append(f"scale=-2:{resolution}")
    vf_filter_str = ",".join(vf_filters)
    primary_kwargs = {"vf": vf_filter_str, "acodec": "copy"}
    fallback_kwargs = {"vf": vf_filter_str}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def set_video_codec(
    input_video_path: str, output_video_path: str, video_codec: str
) -> str:
    """Sets the video codec of a video."""
    primary_kwargs = {"vcodec": video_codec, "acodec": "copy"}
    fallback_kwargs = {"vcodec": video_codec}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def set_video_bitrate(
    input_video_path: str, output_video_path: str, video_bitrate: str
) -> str:
    """Sets the video bitrate of a video."""
    primary_kwargs = {"video_bitrate": video_bitrate, "acodec": "copy"}
    fallback_kwargs = {"video_bitrate": video_bitrate}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def set_video_frame_rate(
    input_video_path: str, output_video_path: str, frame_rate: int
) -> str:
    """Sets the frame rate of a video."""
    primary_kwargs = {"r": frame_rate, "acodec": "copy"}
    fallback_kwargs = {"r": frame_rate}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


# ---- Audio Tools ----

@app.tool()
def convert_audio_format(
    input_audio_path: str, output_audio_path: str, target_format: str
) -> str:
    """Converts an audio file to the specified target format."""
    try:
        ffmpeg.input(input_audio_path).output(
            output_audio_path, format=target_format
        ).run(capture_stdout=True, capture_stderr=True)
        return f"Audio format converted to {target_format} and saved to {output_audio_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error converting audio format: {error_message}"
    except FileNotFoundError:
        return f"Error: Input audio file not found at {input_audio_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def convert_audio_properties(
    input_audio_path: str,
    output_audio_path: str,
    target_format: str,
    bitrate: str = None,
    sample_rate: int = None,
    channels: int = None,
) -> str:
    """Converts audio file format and properties."""
    try:
        stream = ffmpeg.input(input_audio_path)
        kwargs = {}
        if bitrate:
            kwargs["audio_bitrate"] = bitrate
        if sample_rate:
            kwargs["ar"] = sample_rate
        if channels:
            kwargs["ac"] = channels
        kwargs["format"] = target_format
        output_stream = stream.output(output_audio_path, **kwargs)
        output_stream.run(capture_stdout=True, capture_stderr=True)
        return f"Audio converted successfully to {output_audio_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error converting audio properties: {error_message}"
    except FileNotFoundError:
        return f"Error: Input audio file not found at {input_audio_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def set_audio_bitrate(
    input_audio_path: str, output_audio_path: str, bitrate: str
) -> str:
    """Sets the bitrate for an audio file."""
    try:
        ffmpeg.input(input_audio_path).output(
            output_audio_path, audio_bitrate=bitrate
        ).run(capture_stdout=True, capture_stderr=True)
        return f"Audio bitrate set to {bitrate} and saved to {output_audio_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error setting audio bitrate: {error_message}"
    except FileNotFoundError:
        return f"Error: Input audio file not found at {input_audio_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def set_audio_sample_rate(
    input_audio_path: str, output_audio_path: str, sample_rate: int
) -> str:
    """Sets the sample rate for an audio file."""
    try:
        ffmpeg.input(input_audio_path).output(
            output_audio_path, ar=sample_rate
        ).run(capture_stdout=True, capture_stderr=True)
        return f"Audio sample rate set to {sample_rate} Hz and saved to {output_audio_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error setting audio sample rate: {error_message}"
    except FileNotFoundError:
        return f"Error: Input audio file not found at {input_audio_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def set_audio_channels(
    input_audio_path: str, output_audio_path: str, channels: int
) -> str:
    """Sets the number of channels for an audio file."""
    try:
        ffmpeg.input(input_audio_path).output(
            output_audio_path, ac=channels
        ).run(capture_stdout=True, capture_stderr=True)
        return f"Audio channels set to {channels} and saved to {output_audio_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error setting audio channels: {error_message}"
    except FileNotFoundError:
        return f"Error: Input audio file not found at {input_audio_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


# ---- Video Audio Track Tools ----

@app.tool()
def set_video_audio_track_codec(
    input_video_path: str, output_video_path: str, audio_codec: str
) -> str:
    """Sets the audio codec of a video's audio track."""
    primary_kwargs = {"acodec": audio_codec, "vcodec": "copy"}
    fallback_kwargs = {"acodec": audio_codec}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def set_video_audio_track_bitrate(
    input_video_path: str, output_video_path: str, audio_bitrate: str
) -> str:
    """Sets the audio bitrate of a video's audio track."""
    primary_kwargs = {"audio_bitrate": audio_bitrate, "vcodec": "copy"}
    fallback_kwargs = {"audio_bitrate": audio_bitrate}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def set_video_audio_track_sample_rate(
    input_video_path: str, output_video_path: str, audio_sample_rate: int
) -> str:
    """Sets the audio sample rate of a video's audio track."""
    primary_kwargs = {"ar": audio_sample_rate, "vcodec": "copy"}
    fallback_kwargs = {"ar": audio_sample_rate}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


@app.tool()
def set_video_audio_track_channels(
    input_video_path: str, output_video_path: str, audio_channels: int
) -> str:
    """Sets the number of audio channels of a video's audio track."""
    primary_kwargs = {"ac": audio_channels, "vcodec": "copy"}
    fallback_kwargs = {"ac": audio_channels}
    return _run_ffmpeg_with_fallback(
        input_video_path, output_video_path, primary_kwargs, fallback_kwargs
    )


# ---- Creative Tools ----

@app.tool()
def add_subtitles(
    video_path: str,
    srt_file_path: str,
    output_video_path: str,
    font_style: dict = None,
) -> str:
    """Burns subtitles from an SRT file onto a video."""
    try:
        if not os.path.exists(video_path):
            return f"Error: Input video file not found at {video_path}"
        if not os.path.exists(srt_file_path):
            return f"Error: SRT subtitle file not found at {srt_file_path}"

        input_stream = ffmpeg.input(video_path)
        style_args = []
        if font_style:
            style_map = {
                "font_name": "FontName",
                "font_size": "FontSize",
                "font_color": "PrimaryColour",
                "outline_color": "OutlineColour",
                "outline_width": "Outline",
                "shadow_color": "ShadowColour",
                "alignment": "Alignment",
                "margin_v": "MarginV",
                "margin_l": "MarginL",
                "margin_r": "MarginR",
            }
            for key, ass_key in style_map.items():
                if key in font_style:
                    style_args.append(f"{ass_key}={font_style[key]}")
            if "shadow_offset_x" in font_style or "shadow_offset_y" in font_style:
                shadow_val = font_style.get(
                    "shadow_offset_x", font_style.get("shadow_offset_y", 1)
                )
                style_args.append(f"Shadow={shadow_val}")

        vf_filter_value = f"subtitles='{srt_file_path}'"
        if style_args:
            vf_filter_value += f":force_style='{','.join(style_args)}'"

        output_stream = input_stream.output(
            output_video_path, vf=vf_filter_value, acodec="copy"
        )
        try:
            output_stream.run(capture_stdout=True, capture_stderr=True)
            return f"Subtitles added successfully (audio copied) to {output_video_path}"
        except ffmpeg.Error as e_acopy:
            output_stream_recode = input_stream.output(
                output_video_path, vf=vf_filter_value
            )
            try:
                output_stream_recode.run(capture_stdout=True, capture_stderr=True)
                return f"Subtitles added successfully (audio re-encoded) to {output_video_path}"
            except ffmpeg.Error as e_recode_all:
                err_acopy_msg = (
                    e_acopy.stderr.decode("utf8") if e_acopy.stderr else str(e_acopy)
                )
                err_recode_msg = (
                    e_recode_all.stderr.decode("utf8")
                    if e_recode_all.stderr
                    else str(e_recode_all)
                )
                return f"Error adding subtitles. Audio copy attempt: {err_acopy_msg}. Full re-encode attempt: {err_recode_msg}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error adding subtitles: {error_message}"
    except FileNotFoundError:
        return "Error: A specified file was not found."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def add_text_overlay(
    video_path: str, output_video_path: str, text_elements: list[dict]
) -> str:
    """Adds one or more text overlays to a video at specified times."""
    try:
        if not os.path.exists(video_path):
            return f"Error: Input video file not found at {video_path}"
        if not text_elements:
            return "Error: No text elements provided for overlay."

        input_stream = ffmpeg.input(video_path)
        drawtext_filters = []
        for element in text_elements:
            text = element.get("text")
            start_time = element.get("start_time")
            end_time = element.get("end_time")
            if text is None or start_time is None or end_time is None:
                return "Error: Text element missing required keys."
            safe_text = (
                text.replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace(",", "\\,")
            )
            filter_params = [
                f"text='{safe_text}'",
                f"fontsize={element.get('font_size', 24)}",
                f"fontcolor={element.get('font_color', 'white')}",
                f"x={element.get('x_pos', '(w-text_w)/2')}",
                f"y={element.get('y_pos', 'h-text_h-10')}",
                f"enable=between(t\\,{start_time}\\,{end_time})",
            ]
            if element.get("box", False):
                filter_params.append("box=1")
                filter_params.append(
                    f"boxcolor={element.get('box_color', 'black@0.5')}"
                )
                if "box_border_width" in element:
                    filter_params.append(
                        f"boxborderw={element['box_border_width']}"
                    )
            if "font_file" in element:
                font_path = (
                    element["font_file"]
                    .replace("\\", "\\\\")
                    .replace("'", "\\'")
                    .replace(":", "\\:")
                )
                filter_params.append(f"fontfile='{font_path}'")
            drawtext_filter = f"drawtext={':'.join(filter_params)}"
            drawtext_filters.append(drawtext_filter)

        final_vf_filter = ",".join(drawtext_filters)
        try:
            stream = input_stream.output(
                output_video_path, vf=final_vf_filter, acodec="copy"
            )
            stream.run(capture_stdout=True, capture_stderr=True)
            return f"Text overlays added successfully (audio copied) to {output_video_path}"
        except ffmpeg.Error as e_acopy:
            try:
                stream_recode = input_stream.output(
                    output_video_path, vf=final_vf_filter
                )
                stream_recode.run(capture_stdout=True, capture_stderr=True)
                return f"Text overlays added successfully (audio re-encoded) to {output_video_path}"
            except ffmpeg.Error as e_recode_all:
                err_acopy_msg = (
                    e_acopy.stderr.decode("utf8") if e_acopy.stderr else str(e_acopy)
                )
                err_recode_msg = (
                    e_recode_all.stderr.decode("utf8")
                    if e_recode_all.stderr
                    else str(e_recode_all)
                )
                return f"Error adding text overlays. Audio copy: {err_acopy_msg}. Re-encode: {err_recode_msg}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error processing text overlays: {error_message}"
    except FileNotFoundError:
        return "Error: Input video file not found."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def add_image_overlay(
    video_path: str,
    output_video_path: str,
    image_path: str,
    position: str = "top_right",
    opacity: float = None,
    start_time: str = None,
    end_time: str = None,
    width: str = None,
    height: str = None,
) -> str:
    """Adds an image overlay (watermark/logo) to a video."""
    try:
        if not os.path.exists(video_path):
            return f"Error: Input video file not found at {video_path}"
        if not os.path.exists(image_path):
            return f"Error: Overlay image file not found at {image_path}"

        main_input = ffmpeg.input(video_path)
        overlay_input = ffmpeg.input(image_path)

        processed_overlay = overlay_input
        if width or height:
            scale_params = {}
            if width:
                scale_params["width"] = width
            if height:
                scale_params["height"] = height
            if width and not height:
                scale_params["height"] = "-1"
            if height and not width:
                scale_params["width"] = "-1"
            processed_overlay = processed_overlay.filter("scale", **scale_params)

        if opacity is not None and 0.0 <= opacity <= 1.0:
            processed_overlay = processed_overlay.filter("format", "rgba")
            processed_overlay = processed_overlay.filter(
                "colorchannelmixer", aa=str(opacity)
            )

        position_map = {
            "top_left": ("10", "10"),
            "top_right": ("main_w-overlay_w-10", "10"),
            "bottom_left": ("10", "main_h-overlay_h-10"),
            "bottom_right": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
            "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
        }
        if position in position_map:
            overlay_x_pos, overlay_y_pos = position_map[position]
        elif ":" in position:
            overlay_x_pos, overlay_y_pos = "0", "0"
            for part in position.split(":"):
                if part.startswith("x="):
                    overlay_x_pos = part.split("=")[1]
                if part.startswith("y="):
                    overlay_y_pos = part.split("=")[1]
        else:
            overlay_x_pos, overlay_y_pos = "0", "0"

        overlay_filter_kwargs = {"x": overlay_x_pos, "y": overlay_y_pos}
        if start_time is not None or end_time is not None:
            actual_start_time = start_time if start_time is not None else "0"
            if end_time is not None:
                enable_expr = f"between(t,{actual_start_time},{end_time})"
            else:
                enable_expr = f"gte(t,{actual_start_time})"
            overlay_filter_kwargs["enable"] = enable_expr

        try:
            video_with_overlay = ffmpeg.filter(
                [main_input, processed_overlay], "overlay", **overlay_filter_kwargs
            )
            output_node = ffmpeg.output(
                video_with_overlay, main_input.audio, output_video_path, acodec="copy"
            )
            output_node.run(capture_stdout=True, capture_stderr=True)
            return f"Image overlay added (audio copied) to {output_video_path}"
        except ffmpeg.Error as e_acopy:
            try:
                video_with_overlay_fallback = ffmpeg.filter(
                    [main_input, processed_overlay],
                    "overlay",
                    **overlay_filter_kwargs,
                )
                output_node_fallback = ffmpeg.output(
                    video_with_overlay_fallback,
                    main_input.audio,
                    output_video_path,
                )
                output_node_fallback.run(capture_stdout=True, capture_stderr=True)
                return f"Image overlay added (audio re-encoded) to {output_video_path}"
            except ffmpeg.Error as e_recode:
                err_acopy_msg = (
                    e_acopy.stderr.decode("utf8") if e_acopy.stderr else str(e_acopy)
                )
                err_recode_msg = (
                    e_recode.stderr.decode("utf8")
                    if e_recode.stderr
                    else str(e_recode)
                )
                return f"Error adding overlay. Audio copy: {err_acopy_msg}. Re-encode: {err_recode_msg}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error processing image overlay: {error_message}"
    except FileNotFoundError:
        return "Error: An input file was not found."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@app.tool()
def concatenate_videos(
    video_paths: list[str],
    output_video_path: str,
    transition_effect: str = None,
    transition_duration: float = None,
) -> str:
    """Concatenates multiple video files into a single output file."""
    if not video_paths:
        return "Error: No video paths provided."
    if transition_effect and transition_duration is None:
        return "Error: transition_duration required with transition_effect."
    if transition_effect and transition_duration <= 0:
        return "Error: transition_duration must be positive."

    valid_transitions = {
        "dissolve", "fade", "fadeblack", "fadewhite", "fadegrays", "distance",
        "wipeleft", "wiperight", "wipeup", "wipedown",
        "slideleft", "slideright", "slideup", "slidedown",
        "smoothleft", "smoothright", "smoothup", "smoothdown",
        "circlecrop", "rectcrop", "circleopen", "circleclose",
        "vertopen", "vertclose", "horzopen", "horzclose",
        "diagtl", "diagtr", "diagbl", "diagbr",
        "hlslice", "hrslice", "vuslice", "vdslice",
        "pixelize", "radial", "hblur",
    }
    if transition_effect and transition_effect not in valid_transitions:
        return f"Error: Invalid transition_effect. Valid options: {', '.join(sorted(valid_transitions))}"

    for video_path in video_paths:
        if not os.path.exists(video_path):
            return f"Error: Video not found at {video_path}"

    if len(video_paths) == 1:
        try:
            ffmpeg.input(video_paths[0]).output(
                output_video_path, vcodec="libx264", acodec="aac"
            ).run(capture_stdout=True, capture_stderr=True)
            return f"Single video processed to {output_video_path}"
        except ffmpeg.Error as e:
            return f"Error: {e.stderr.decode('utf8') if e.stderr else str(e)}"

    if transition_effect and len(video_paths) == 2:
        temp_dir = tempfile.mkdtemp()
        try:
            props1 = _get_media_properties(video_paths[0])
            props2 = _get_media_properties(video_paths[1])
            if not props1["has_video"] or not props2["has_video"]:
                return "Error: xfade requires both inputs to be videos."
            if transition_duration >= props1["duration"]:
                return "Error: Transition duration too long."

            has_audio = props1["has_audio"] and props2["has_audio"]
            target_w = max(props1["width"], props2["width"], 640)
            target_h = max(props1["height"], props2["height"], 360)
            target_fps = max(props1["avg_fps"], props2["avg_fps"], 30)
            if target_fps <= 0:
                target_fps = 30

            norm_paths = []
            for i, vp in enumerate(video_paths):
                norm_path = os.path.join(temp_dir, f"norm_video{i}.mp4")
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-i", vp,
                            "-vf", f"scale={target_w}:{target_h}",
                            "-r", str(target_fps),
                            "-c:v", "libx264", "-c:a", "aac",
                            "-y", norm_path,
                        ],
                        check=True, capture_output=True,
                    )
                    norm_paths.append(norm_path)
                except subprocess.CalledProcessError:
                    return f"Error normalizing video {i}."

            norm_props1 = _get_media_properties(norm_paths[0])
            if transition_duration >= norm_props1["duration"]:
                return "Error: Transition duration too long."

            offset = norm_props1["duration"] - transition_duration
            filter_complex = f"[0:v][1:v]xfade=transition={transition_effect}:duration={transition_duration}:offset={offset}"

            cmd = ["ffmpeg", "-i", norm_paths[0], "-i", norm_paths[1], "-filter_complex"]
            if has_audio:
                filter_complex += f",[0:a][1:a]acrossfade=d={transition_duration}:c1=tri:c2=tri"
                cmd.extend([filter_complex, "-map", "[v]", "-map", "[a]"])
            else:
                filter_complex += "[v]"
                cmd.extend([filter_complex, "-map", "[v]"])

            cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-y", output_video_path])
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return f"Videos concatenated with transition to {output_video_path}"
            except subprocess.CalledProcessError:
                return "Error during xfade process."
        except Exception as e:
            return f"Unexpected error: {str(e)}"
        finally:
            shutil.rmtree(temp_dir)

    elif transition_effect and len(video_paths) > 2:
        return "Error: xfade supports only two videos."

    # Standard concatenation (no transitions)
    temp_dir = tempfile.mkdtemp()
    try:
        first_props = _get_media_properties(video_paths[0])
        target_w = first_props["width"] if first_props["width"] > 0 else 1280
        target_h = first_props["height"] if first_props["height"] > 0 else 720
        target_fps = first_props["avg_fps"] if first_props["avg_fps"] > 0 else 30
        if target_fps <= 0:
            target_fps = 30

        normalized_paths = []
        for i, video_path in enumerate(video_paths):
            norm_path = os.path.join(temp_dir, f"norm_{i}.mp4")
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-i", video_path,
                        "-vf", f"scale={target_w}:{target_h}",
                        "-r", str(target_fps),
                        "-c:v", "libx264", "-c:a", "aac",
                        "-y", norm_path,
                    ],
                    check=True, capture_output=True,
                )
                normalized_paths.append(norm_path)
            except subprocess.CalledProcessError:
                return f"Error normalizing video {i}."

        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w") as f:
            for path in normalized_paths:
                f.write(f"file '{path}'\n")

        try:
            subprocess.run(
                [
                    "ffmpeg", "-f", "concat", "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy", "-y", output_video_path,
                ],
                check=True, capture_output=True,
            )
            return f"Videos concatenated to {output_video_path}"
        except subprocess.CalledProcessError:
            return "Error during concatenation."
    except Exception as e:
        return f"Unexpected error: {str(e)}"
    finally:
        shutil.rmtree(temp_dir)


@app.tool()
def change_video_speed(
    video_path: str, output_video_path: str, speed_factor: float
) -> str:
    """Changes the playback speed of a video and its audio."""
    if speed_factor <= 0:
        return "Error: Speed factor must be positive."
    if not os.path.exists(video_path):
        return f"Error: Video not found at {video_path}"
    try:
        atempo_value = speed_factor
        atempo_filters = []
        if speed_factor < 0.5:
            while atempo_value < 0.5:
                atempo_filters.append("atempo=0.5")
                atempo_value *= 2
            if atempo_value < 0.99:
                atempo_filters.append(f"atempo={atempo_value}")
        elif speed_factor > 2.0:
            while atempo_value > 2.0:
                atempo_filters.append("atempo=2.0")
                atempo_value /= 2
            if atempo_value > 1.01:
                atempo_filters.append(f"atempo={atempo_value}")
        else:
            atempo_filters.append(f"atempo={speed_factor}")

        input_stream = ffmpeg.input(video_path)
        video = input_stream.video.setpts(f"{1.0/speed_factor}*PTS")
        audio = input_stream.audio
        for filter_str in atempo_filters:
            val = float(filter_str.replace("atempo=", ""))
            audio = audio.filter("atempo", val)

        output = ffmpeg.output(video, audio, output_video_path)
        output.run(capture_stdout=True, capture_stderr=True)
        return f"Speed changed by {speed_factor} to {output_video_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error: {error_message}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@app.tool()
def remove_silence(
    media_path: str,
    output_media_path: str,
    silence_threshold_db: float = -30.0,
    min_silence_duration_ms: int = 500,
) -> str:
    """Removes silent segments from an audio or video file."""
    if not os.path.exists(media_path):
        return f"Error: File not found at {media_path}"
    if min_silence_duration_ms <= 0:
        return "Error: Silence duration must be positive."

    min_silence_duration_s = min_silence_duration_ms / 1000.0
    try:
        silence_detection_process = (
            ffmpeg.input(media_path)
            .filter(
                "silencedetect", n=f"{silence_threshold_db}dB", d=min_silence_duration_s
            )
            .output("-", format="null")
            .run_async(pipe_stderr=True)
        )
        _, stderr_bytes = silence_detection_process.communicate()
        stderr_str = stderr_bytes.decode("utf8")

        silence_starts = [
            float(x) for x in re.findall(r"silence_start: (\d+\.?\d*)", stderr_str)
        ]
        silence_ends = [
            float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", stderr_str)
        ]

        if not silence_starts:
            try:
                ffmpeg.input(media_path).output(
                    output_media_path, c="copy"
                ).run(capture_stdout=True, capture_stderr=True)
                return f"No silences detected. Original copied to {output_media_path}."
            except ffmpeg.Error:
                return "Error copying file."

        probe = ffmpeg.probe(media_path)
        total_duration = float(probe["format"]["duration"])

        sound_segments = []
        current_pos = 0.0
        for i in range(len(silence_starts)):
            start_silence = silence_starts[i]
            end_silence = (
                silence_ends[i] if i < len(silence_ends) else total_duration
            )
            if start_silence > current_pos:
                sound_segments.append((current_pos, start_silence))
            current_pos = end_silence
        if current_pos < total_duration:
            sound_segments.append((current_pos, total_duration))

        if not sound_segments:
            return "Error: No sound segments identified."

        video_select_parts = []
        audio_select_parts = []
        for start, end in sound_segments:
            video_select_parts.append(f"between(t,{start},{end})")
            audio_select_parts.append(f"between(t,{start},{end})")

        video_select_expr = "+".join(video_select_parts)
        audio_select_expr = "+".join(audio_select_parts)

        input_media = ffmpeg.input(media_path)
        has_video = any(
            s["codec_type"] == "video" for s in probe["streams"]
        )
        has_audio = any(
            s["codec_type"] == "audio" for s in probe["streams"]
        )

        output_streams = []
        if has_video:
            processed_video = (
                input_media.video.filter("select", video_select_expr).filter(
                    "setpts", "PTS-STARTPTS"
                )
            )
            output_streams.append(processed_video)
        if has_audio:
            processed_audio = (
                input_media.audio.filter("aselect", audio_select_expr).filter(
                    "asetpts", "PTS-STARTPTS"
                )
            )
            output_streams.append(processed_audio)

        if not output_streams:
            return "Error: No video or audio streams."

        ffmpeg.output(*output_streams, output_media_path).run(
            capture_stdout=True, capture_stderr=True
        )
        return f"Silence removed. Output saved to {output_media_path}"
    except ffmpeg.Error as e:
        error_message = e.stderr.decode("utf8") if e.stderr else str(e)
        return f"Error: {error_message}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@app.tool()
def add_b_roll(
    main_video_path: str, broll_clips: list[dict], output_video_path: str
) -> str:
    """Inserts B-roll clips into a main video as overlays."""
    if not os.path.exists(main_video_path):
        return "Error: Main video not found."
    if not broll_clips:
        try:
            ffmpeg.input(main_video_path).output(
                output_video_path, c="copy"
            ).run(capture_stdout=True, capture_stderr=True)
            return "No B-roll clips provided. Main video copied."
        except ffmpeg.Error:
            return "Error copying main video."

    valid_positions = {
        "fullscreen", "top-left", "top-right", "bottom-left", "bottom-right", "center"
    }

    try:
        temp_dir = tempfile.mkdtemp()
        try:
            main_props = _get_media_properties(main_video_path)
            if not main_props["has_video"]:
                return "Error: Main video has no video stream."

            main_width = main_props["width"]
            main_height = main_props["height"]

            processed_clips = []
            for i, broll_item in enumerate(
                sorted(
                    broll_clips,
                    key=lambda x: _parse_time_to_seconds(x["insert_at_timestamp"]),
                )
            ):
                clip_path = broll_item["clip_path"]
                if not os.path.exists(clip_path):
                    return "Error: B-roll not found."
                broll_props = _get_media_properties(clip_path)
                if not broll_props["has_video"]:
                    continue

                start_time = _parse_time_to_seconds(
                    broll_item["insert_at_timestamp"]
                )
                duration = _parse_time_to_seconds(
                    broll_item.get("duration", str(broll_props["duration"]))
                )
                position = broll_item.get("position", "fullscreen")
                if position not in valid_positions:
                    return "Error: Invalid position."

                temp_clip = os.path.join(temp_dir, f"processed_broll_{i}.mp4")
                scale_factor = broll_item.get(
                    "scale", 1.0 if position == "fullscreen" else 0.5
                )

                scale_filter_parts = []
                if position == "fullscreen":
                    scale_filter_parts.append(f"scale={main_width}:{main_height}")
                else:
                    scale_filter_parts.append(
                        f"scale=iw*{scale_factor}:ih*{scale_factor}"
                    )

                transition_in = broll_item.get("transition_in")
                transition_out = broll_item.get("transition_out")
                transition_duration = float(
                    broll_item.get("transition_duration", 0.5)
                )

                if transition_in == "fade":
                    scale_filter_parts.append(
                        f"fade=t=in:st=0:d={transition_duration}"
                    )
                if transition_out == "fade":
                    fade_out_start = max(
                        0, float(broll_props["duration"]) - transition_duration
                    )
                    scale_filter_parts.append(
                        f"fade=t=out:st={fade_out_start}:d={transition_duration}"
                    )

                filter_string = ",".join(scale_filter_parts)
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-i", clip_path,
                            "-vf", filter_string,
                            "-c:v", "libx264", "-c:a", "aac",
                            "-y", temp_clip,
                        ],
                        check=True, capture_output=True,
                    )
                except subprocess.CalledProcessError:
                    return f"Error processing B-roll {i}."

                position_map = {
                    "fullscreen": ("0", "0"),
                    "top-left": ("10", "10"),
                    "top-right": ("W-w-10", "10"),
                    "bottom-left": ("10", "H-h-10"),
                    "bottom-right": ("W-w-10", "H-h-10"),
                    "center": ("(W-w)/2", "(H-h)/2"),
                }
                overlay_x, overlay_y = position_map.get(position, ("0", "0"))

                processed_clips.append(
                    {
                        "path": temp_clip,
                        "start_time": start_time,
                        "duration": duration,
                        "overlay_x": overlay_x,
                        "overlay_y": overlay_y,
                    }
                )

            if not processed_clips:
                try:
                    shutil.copy(main_video_path, output_video_path)
                    return "No valid clips. Main video copied."
                except Exception:
                    return "Error copying main video."

            filter_parts = []
            main_overlay = "[0:v]"
            for i, clip in enumerate(processed_clips):
                overlay_index = i + 1
                overlay_filter = (
                    f"{main_overlay}[{overlay_index}:v]overlay="
                    f"x={clip['overlay_x']}:y={clip['overlay_y']}:"
                    f"enable='between(t,{clip['start_time']},{clip['start_time'] + clip['duration']})'"
                )
                if i < len(processed_clips) - 1:
                    current_label = f"[v{i}]"
                    overlay_filter += current_label
                    main_overlay = current_label
                else:
                    overlay_filter += "[v]"
                filter_parts.append(overlay_filter)

            filter_complex = ";".join(filter_parts)

            audio_output = []
            if main_props["has_audio"]:
                audio_output = ["-map", "0:a"]

            input_files = ["-i", main_video_path]
            for clip in processed_clips:
                input_files.extend(["-i", clip["path"]])

            cmd = [
                "ffmpeg", *input_files,
                "-filter_complex", filter_complex,
                "-map", "[v]", *audio_output,
                "-c:v", "libx264", "-c:a", "aac",
                "-y", output_video_path,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return f"B-roll added. Output: {output_video_path}"
            except subprocess.CalledProcessError:
                return "Error in final composition."
        finally:
            shutil.rmtree(temp_dir)
    except ffmpeg.Error:
        return "Error: FFmpeg error."
    except ValueError:
        return "Error with input values."
    except RuntimeError:
        return "Runtime error."
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@app.tool()
def add_basic_transitions(
    video_path: str,
    output_video_path: str,
    transition_type: str,
    duration_seconds: float,
) -> str:
    """Adds basic fade transitions."""
    if not os.path.exists(video_path):
        return "Error: Video not found."
    if duration_seconds <= 0:
        return "Error: Duration must be positive."
    try:
        props = _get_media_properties(video_path)
        video_total_duration = props["duration"]
        if duration_seconds > video_total_duration:
            return "Error: Transition duration exceeds video duration."

        input_stream = ffmpeg.input(video_path)
        video_stream = input_stream.video
        audio_stream = input_stream.audio

        if transition_type in ("fade_in", "crossfade_from_black"):
            processed_video = video_stream.filter(
                "fade", type="in", start_time=0, duration=duration_seconds
            )
        elif transition_type in ("fade_out", "crossfade_to_black"):
            fade_start_time = video_total_duration - duration_seconds
            processed_video = video_stream.filter(
                "fade",
                type="out",
                start_time=fade_start_time,
                duration=duration_seconds,
            )
        else:
            return "Error: Unsupported transition type."

        output_streams = []
        if props["has_video"]:
            output_streams.append(processed_video)
        if props["has_audio"]:
            output_streams.append(audio_stream)

        if not output_streams:
            return "Error: No streams."

        try:
            ffmpeg.output(*output_streams, output_video_path, acodec="copy").run(
                capture_stdout=True, capture_stderr=True
            )
            return f"Transition applied (audio copied). Output: {output_video_path}"
        except ffmpeg.Error:
            try:
                ffmpeg.output(*output_streams, output_video_path).run(
                    capture_stdout=True, capture_stderr=True
                )
                return f"Transition applied (audio processed). Output: {output_video_path}"
            except ffmpeg.Error:
                return "Error applying transition."
    except ffmpeg.Error:
        return "Error: FFmpeg error."
    except ValueError:
        return "Error with values."
    except RuntimeError:
        return "Runtime error."
    except Exception as e:
        return f"Unexpected error: {str(e)}"


# ---- Helper Functions ----

def _run_ffmpeg_with_fallback(
    input_path: str,
    output_path: str,
    primary_kwargs: dict,
    fallback_kwargs: dict,
) -> str:
    """Helper to run ffmpeg command with primary kwargs, falling back on failure."""
    try:
        ffmpeg.input(input_path).output(output_path, **primary_kwargs).run(
            capture_stdout=True, capture_stderr=True
        )
        return f"Operation successful (primary method) and saved to {output_path}"
    except ffmpeg.Error as e_primary:
        try:
            ffmpeg.input(input_path).output(output_path, **fallback_kwargs).run(
                capture_stdout=True, capture_stderr=True
            )
            return f"Operation successful (fallback method) and saved to {output_path}"
        except ffmpeg.Error as e_fallback:
            err_primary_msg = (
                e_primary.stderr.decode("utf8")
                if e_primary.stderr
                else str(e_primary)
            )
            err_fallback_msg = (
                e_fallback.stderr.decode("utf8")
                if e_fallback.stderr
                else str(e_fallback)
            )
            return f"Error. Primary method failed: {err_primary_msg}. Fallback method also failed: {err_fallback_msg}"
    except FileNotFoundError:
        return f"Error: Input file not found at {input_path}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


def _parse_time_to_seconds(time_str: str) -> float:
    """Converts HH:MM:SS.mmm or seconds string to float seconds."""
    if isinstance(time_str, (int, float)):
        return float(time_str)
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        else:
            raise ValueError(f"Invalid time format: {time_str}")
    return float(time_str)


def _get_media_properties(media_path: str) -> dict:
    """Probes media file and returns key properties."""
    try:
        probe = ffmpeg.probe(media_path)
        video_stream_info = next(
            (s for s in probe["streams"] if s["codec_type"] == "video"), None
        )
        audio_stream_info = next(
            (s for s in probe["streams"] if s["codec_type"] == "audio"), None
        )
        props = {
            "duration": float(probe["format"].get("duration", 0.0)),
            "has_video": video_stream_info is not None,
            "has_audio": audio_stream_info is not None,
            "width": (
                int(video_stream_info["width"])
                if video_stream_info and "width" in video_stream_info
                else 0
            ),
            "height": (
                int(video_stream_info["height"])
                if video_stream_info and "height" in video_stream_info
                else 0
            ),
            "avg_fps": 0,
            "sample_rate": (
                int(audio_stream_info["sample_rate"])
                if audio_stream_info and "sample_rate" in audio_stream_info
                else 44100
            ),
            "channels": (
                int(audio_stream_info["channels"])
                if audio_stream_info and "channels" in audio_stream_info
                else 2
            ),
            "channel_layout": (
                audio_stream_info.get("channel_layout", "stereo")
                if audio_stream_info
                else "stereo"
            ),
        }
        if (
            video_stream_info
            and "avg_frame_rate" in video_stream_info
            and video_stream_info["avg_frame_rate"] != "0/0"
        ):
            num, den = map(int, video_stream_info["avg_frame_rate"].split("/"))
            props["avg_fps"] = num / den if den > 0 else 30
        else:
            props["avg_fps"] = 30
        return props
    except ffmpeg.Error:
        raise RuntimeError(f"Error probing file {media_path}")
    except Exception:
        raise RuntimeError(f"Unexpected error probing {media_path}")


# ---- Server Entry Point ----

def main(transport: str = "stdio", port: int = 8000):
    if transport == "http":
        import uvicorn
        from mcp.server.transport_security import TransportSecuritySettings
        from starlette.routing import Route
        from starlette.responses import FileResponse, JSONResponse

        # HTTP download endpoint for processed files
        async def download_endpoint(request):
            filename = request.path_params["filename"]
            safe_filename = os.path.basename(filename)
            file_path = os.path.join(DOWNLOAD_DIR, safe_filename)
            if not os.path.exists(file_path):
                return JSONResponse(
                    {"error": f"File not found: {safe_filename}"}, status_code=404
                )
            # Determine MIME type from extension
            ext = os.path.splitext(safe_filename)[1].lower()
            mime_types = {
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".avi": "video/x-msvideo",
                ".mkv": "video/x-matroska",
                ".webm": "video/webm",
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
                ".aac": "audio/aac",
                ".ogg": "audio/ogg",
                ".flac": "audio/flac",
                ".m4a": "audio/mp4",
            }
            media_type = mime_types.get(ext, "application/octet-stream")
            return FileResponse(
                file_path, media_type=media_type, filename=safe_filename
            )

        # Health endpoint
        async def health(request):
            return JSONResponse(
                {"status": "ok", "server": "video-audio-mcp-server"}
            )

        # Configure FastMCP settings
        app.settings.host = "0.0.0.0"
        app.settings.port = port
        app.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

        # Get the MCP Starlette app and add custom routes
        mcp_starlette = app.streamable_http_app()
        mcp_starlette.routes.insert(0, Route("/health", health))
        mcp_starlette.routes.insert(
            1, Route("/download/{filename:path}", download_endpoint)
        )

        try:
            uvicorn.run(mcp_starlette, host="0.0.0.0", port=port)
        except KeyboardInterrupt:
            print("Server stopped by user.")
        except Exception as e:
            print(f"Error starting server: {e}")

    elif transport == "sse":
        app.run(transport="sse")

    else:
        app.run(transport="stdio")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MCP Server for Video and Audio editing using FFmpeg"
    )
    parser.add_argument(
        "-t", "--transport",
        type=str, default="stdio",
        choices=["stdio", "http", "sse"],
        help="Transport method for the MCP server (default: stdio)",
    )
    parser.add_argument(
        "-p", "--port",
        type=int, default=8000,
        help="Port to run the MCP server on (default: 8000)",
    )
    args = parser.parse_args()
    main(args.transport, args.port)
