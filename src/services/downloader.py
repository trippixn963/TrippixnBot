"""
TrippixnBot - Downloader Service
================================

Downloads media from Instagram, Twitter/X, and TikTok using yt-dlp.
Compresses videos if they exceed Discord's file size limit.

Author: حَـــــنَّـــــا
"""

import asyncio
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core import log

# Get yt-dlp path from the same venv as the running Python
YTDLP_PATH = str(Path(sys.executable).parent / "yt-dlp")

# Cookies file for Instagram authentication
COOKIES_FILE = Path(__file__).parent.parent.parent / "cookies.txt"


# =============================================================================
# Constants
# =============================================================================

MAX_FILE_SIZE_MB = 24  # Leave some headroom under Discord's 25MB limit
TEMP_DIR = Path(tempfile.gettempdir()) / "trippixn_dl"

# Platform detection patterns
PLATFORM_PATTERNS = {
    "instagram": [
        r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels|stories)/[\w-]+",
        r"(?:https?://)?(?:www\.)?instagram\.com/[\w.]+/(?:p|reel)/[\w-]+",
    ],
    "twitter": [
        r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/\w+/status/\d+",
        r"(?:https?://)?(?:mobile\.)?(?:twitter|x)\.com/\w+/status/\d+",
    ],
    "tiktok": [
        r"(?:https?://)?(?:www\.)?tiktok\.com/@[\w.]+/video/\d+",
        r"(?:https?://)?(?:vm|vt)\.tiktok\.com/[\w]+",
        r"(?:https?://)?(?:www\.)?tiktok\.com/t/[\w]+",
    ],
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DownloadResult:
    """Result of a download operation."""
    success: bool
    files: list[Path]
    platform: str
    error: Optional[str] = None


# =============================================================================
# Downloader Service
# =============================================================================

class DownloaderService:
    """Service for downloading and processing social media content."""

    def __init__(self):
        # Ensure temp directory exists
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

    def get_platform(self, url: str) -> Optional[str]:
        """Detect which platform a URL belongs to."""
        for platform, patterns in PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, url, re.IGNORECASE):
                    return platform
        return None

    async def download(self, url: str) -> DownloadResult:
        """
        Download media from a social media URL.

        Args:
            url: The URL to download from

        Returns:
            DownloadResult with files and status
        """
        platform = self.get_platform(url)
        if not platform:
            return DownloadResult(
                success=False,
                files=[],
                platform="unknown",
                error="Unsupported URL. Only Instagram, Twitter/X, and TikTok are supported."
            )

        # Create unique download directory
        download_id = str(uuid.uuid4())[:8]
        download_dir = TEMP_DIR / download_id
        download_dir.mkdir(parents=True, exist_ok=True)

        log.tree("Starting Download", [
            ("Platform", platform.title()),
            ("URL", url[:60] + "..." if len(url) > 60 else url),
            ("Download Dir", str(download_dir)),
        ], emoji="📥")

        try:
            # Build yt-dlp command
            output_template = str(download_dir / "%(title).50s_%(id)s.%(ext)s")

            cmd = [
                YTDLP_PATH,
                "--no-warnings",
                "--no-playlist",
                "-o", output_template,
                "--restrict-filenames",  # Safe filenames
                "--max-filesize", "100M",  # Don't download huge files
            ]

            # Platform-specific options
            if platform == "instagram":
                # Instagram requires cookies for authentication
                if COOKIES_FILE.exists():
                    cmd.extend(["--cookies", str(COOKIES_FILE)])
                cmd.extend(["--no-check-certificates"])
            elif platform == "tiktok":
                # TikTok sometimes needs special handling
                cmd.extend(["--no-check-certificates"])

            cmd.append(url)

            # Run yt-dlp
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120  # 2 minute timeout
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip() or "Download failed"
                # Clean up common error messages
                if "Private" in error_msg or "login" in error_msg.lower():
                    error_msg = "This content is private or requires login."
                elif "not found" in error_msg.lower() or "404" in error_msg:
                    error_msg = "Content not found. It may have been deleted."
                elif "age" in error_msg.lower():
                    error_msg = "This content is age-restricted."
                else:
                    # Truncate long error messages
                    error_msg = error_msg[:200] if len(error_msg) > 200 else error_msg

                log.warning(f"yt-dlp failed: {error_msg}")
                self.cleanup([download_dir])
                return DownloadResult(
                    success=False,
                    files=[],
                    platform=platform,
                    error=error_msg
                )

            # Get downloaded files
            files = list(download_dir.glob("*"))
            if not files:
                self.cleanup([download_dir])
                return DownloadResult(
                    success=False,
                    files=[],
                    platform=platform,
                    error="No media found in this post."
                )

            log.tree("Download Complete", [
                ("Files", len(files)),
                ("Platform", platform.title()),
            ], emoji="✅")

            # Process files (compress if needed)
            processed_files = []
            for file in files:
                processed = await self._process_file(file)
                if processed:
                    processed_files.append(processed)

            if not processed_files:
                self.cleanup([download_dir])
                return DownloadResult(
                    success=False,
                    files=[],
                    platform=platform,
                    error="All files were too large to upload."
                )

            return DownloadResult(
                success=True,
                files=processed_files,
                platform=platform
            )

        except asyncio.TimeoutError:
            self.cleanup([download_dir])
            return DownloadResult(
                success=False,
                files=[],
                platform=platform,
                error="Download timed out. The file may be too large."
            )
        except Exception as e:
            log.error("Download Error", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
            self.cleanup([download_dir])
            return DownloadResult(
                success=False,
                files=[],
                platform=platform,
                error=f"Download failed: {type(e).__name__}"
            )

    async def _process_file(self, file: Path) -> Optional[Path]:
        """
        Process a downloaded file - compress if too large.

        Args:
            file: Path to the downloaded file

        Returns:
            Path to the processed file, or None if it couldn't be processed
        """
        file_size_mb = file.stat().st_size / (1024 * 1024)

        log.tree("Processing File", [
            ("File", file.name),
            ("Size", f"{file_size_mb:.1f} MB"),
        ], emoji="⚙️")

        # Check if compression is needed
        if file_size_mb <= MAX_FILE_SIZE_MB:
            return file

        # Only compress videos
        video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
        if file.suffix.lower() not in video_extensions:
            log.warning(f"File too large and not a video: {file.name}")
            return None

        # Compress video
        compressed = await self._compress_video(file)
        if compressed:
            # Delete original, return compressed
            file.unlink()
            return compressed

        return None

    async def _compress_video(self, file: Path) -> Optional[Path]:
        """
        Compress a video to fit under the size limit.

        Args:
            file: Path to the video file

        Returns:
            Path to compressed file, or None if compression failed
        """
        log.tree("Compressing Video", [
            ("File", file.name),
            ("Target", f"< {MAX_FILE_SIZE_MB} MB"),
        ], emoji="🗜️")

        output_file = file.parent / f"compressed_{file.stem}.mp4"

        # Calculate target bitrate
        # Get video duration first
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file)
        ]

        try:
            probe_process = await asyncio.create_subprocess_exec(
                *probe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            probe_stdout, _ = await probe_process.communicate()
            duration = float(probe_stdout.decode().strip())
        except Exception:
            duration = 60  # Default to 60 seconds if probe fails

        # Calculate bitrate to hit target size
        target_size_bits = MAX_FILE_SIZE_MB * 8 * 1024 * 1024
        # Leave some room for audio (128kbps)
        audio_bitrate = 128 * 1024
        video_bitrate = int((target_size_bits / duration) - audio_bitrate)
        video_bitrate = max(video_bitrate, 500000)  # Minimum 500kbps

        # FFmpeg compression command
        cmd = [
            "ffmpeg", "-y",
            "-i", str(file),
            "-c:v", "libx264",
            "-preset", "fast",
            "-b:v", str(video_bitrate),
            "-maxrate", str(int(video_bitrate * 1.5)),
            "-bufsize", str(video_bitrate * 2),
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_file)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(
                process.communicate(),
                timeout=300  # 5 minute timeout for compression
            )

            if process.returncode != 0 or not output_file.exists():
                log.warning("FFmpeg compression failed")
                return None

            compressed_size_mb = output_file.stat().st_size / (1024 * 1024)

            log.tree("Compression Complete", [
                ("Original", f"{file.stat().st_size / (1024 * 1024):.1f} MB"),
                ("Compressed", f"{compressed_size_mb:.1f} MB"),
            ], emoji="✅")

            # Check if still too large
            if compressed_size_mb > 25:
                log.warning(f"Compressed file still too large: {compressed_size_mb:.1f} MB")
                output_file.unlink()
                return None

            return output_file

        except asyncio.TimeoutError:
            log.warning("FFmpeg compression timed out")
            if output_file.exists():
                output_file.unlink()
            return None
        except Exception as e:
            log.error("Compression Error", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
            if output_file.exists():
                output_file.unlink()
            return None

    def cleanup(self, paths: list[Path]) -> None:
        """
        Clean up downloaded files and directories.

        Args:
            paths: List of paths to delete
        """
        for path in paths:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except Exception as e:
                log.warning(f"Failed to cleanup {path}: {e}")

    async def get_video_duration(self, file: Path) -> Optional[float]:
        """
        Get video duration in seconds using ffprobe.

        Args:
            file: Path to the video file

        Returns:
            Duration in seconds, or None if not a video/failed
        """
        video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
        if file.suffix.lower() not in video_extensions:
            return None

        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file)
            ]
            process = await asyncio.create_subprocess_exec(
                *probe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            return float(stdout.decode().strip())
        except Exception:
            return None

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Format seconds to MM:SS or HH:MM:SS."""
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """Format bytes to human readable size."""
        size_mb = size_bytes / (1024 * 1024)
        if size_mb >= 1:
            return f"{size_mb:.1f} MB"
        size_kb = size_bytes / 1024
        return f"{size_kb:.0f} KB"


# Global instance
downloader = DownloaderService()
