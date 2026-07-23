"""Video and audio processing using ffmpeg."""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException


# Aggressive compression: 720p, 1 Mbps video, 96 kbps audio
VIDEO_MAX_WIDTH = 1280
VIDEO_MAX_HEIGHT = 720
VIDEO_BITRATE = "900k"
AUDIO_BITRATE = "96k"
VIDEO_CRT = "28"          # ffmpeg CRF — higher = smaller/lower quality
THUMBNAIL_SECOND = "00:00:01"

ACCEPTED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "video/x-matroska", "video/webm", "video/3gpp", "video/mpeg",
}
ACCEPTED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg",
    "audio/wav", "audio/x-wav", "audio/webm", "audio/m4a",
    "audio/x-m4a",
}


@dataclass(frozen=True)
class ProcessedVideo:
    video_bytes: bytes
    thumbnail_bytes: bytes | None
    width: int
    height: int
    duration_seconds: float
    size_bytes: int

    @property
    def content_type(self) -> str:
        return "video/mp4"

    @property
    def extension(self) -> str:
        return ".mp4"

    @property
    def thumbnail_extension(self) -> str:
        return ".jpg"


@dataclass(frozen=True)
class ProcessedAudio:
    audio_bytes: bytes
    duration_seconds: float
    content_type: str
    extension: str
    size_bytes: int


def probe_duration(path: Path) -> float:
    """Return duration in seconds using ffprobe, or 0.0 on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def probe_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) using ffprobe, or (0, 0) on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        parts = result.stdout.strip().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


def process_video(content: bytes, original_suffix: str = ".mp4") -> ProcessedVideo:
    """
    Compress a video to H.264/AAC MP4 at aggressive settings.
    Extract a thumbnail from 1 second in.
    Raises HTTPException on failure.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / f"input{original_suffix}"
        dst = tmp_path / "output.mp4"
        thumb = tmp_path / "thumb.jpg"

        src.write_bytes(content)

        # Compress video
        # Scale to 720p max, keeping aspect ratio; use libx264 + aac
        scale_filter = (
            f"scale='if(gt(iw,{VIDEO_MAX_WIDTH}),{VIDEO_MAX_WIDTH},iw)'"
            f":'if(gt(ih,{VIDEO_MAX_HEIGHT}),{VIDEO_MAX_HEIGHT},ih)'"
            f":force_original_aspect_ratio=decrease"
            f",scale=trunc(iw/2)*2:trunc(ih/2)*2"  # ensure even dims
        )
        compress_result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(src),
                "-vf", scale_filter,
                "-c:v", "libx264", "-crf", VIDEO_CRT, "-preset", "fast",
                "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_BITRATE, "-bufsize", "2M",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-movflags", "+faststart",
                "-f", "mp4", str(dst),
            ],
            capture_output=True, timeout=300,
        )
        if compress_result.returncode != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Video processing failed: {compress_result.stderr[-200:].decode(errors='replace')}",
            )

        # Extract thumbnail
        thumb_bytes: bytes | None = None
        thumb_result = subprocess.run(
            [
                "ffmpeg", "-y", "-ss", THUMBNAIL_SECOND,
                "-i", str(dst),
                "-frames:v", "1", "-q:v", "5",
                str(thumb),
            ],
            capture_output=True, timeout=30,
        )
        if thumb_result.returncode == 0 and thumb.exists():
            thumb_bytes = thumb.read_bytes()

        video_bytes = dst.read_bytes()
        duration = probe_duration(dst)
        width, height = probe_dimensions(dst)

        return ProcessedVideo(
            video_bytes=video_bytes,
            thumbnail_bytes=thumb_bytes,
            width=width,
            height=height,
            duration_seconds=duration,
            size_bytes=len(video_bytes),
        )


def process_audio(content: bytes, content_type: str, original_suffix: str = ".mp3") -> ProcessedAudio:
    """Store audio as-is (no transcoding for voice notes — they're already small)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / f"input{original_suffix}"
        src.write_bytes(content)
        duration = probe_duration(src)

    # Normalise content_type
    ct = content_type.lower()
    if ct in ("audio/m4a", "audio/x-m4a"):
        ct = "audio/mp4"
    ext = {
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
    }.get(ct, original_suffix)

    return ProcessedAudio(
        audio_bytes=content,
        duration_seconds=duration,
        content_type=ct,
        extension=ext,
        size_bytes=len(content),
    )


def get_video_upload_path() -> Path:
    from app.config import get_settings
    settings = get_settings()
    base = Path(settings.photo_upload_dir).parent  # runtime/uploads/
    p = base / "videos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_audio_upload_path() -> Path:
    from app.config import get_settings
    settings = get_settings()
    base = Path(settings.photo_upload_dir).parent
    p = base / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p
