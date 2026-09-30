"""YouTube video metadata and transcript extraction module."""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from pydantic import BaseModel, Field
import yt_dlp
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    CouldNotRetrieveTranscript,
)

logger = logging.getLogger(__name__)


class YouTubeIpBlockedException(Exception):
    """Raised when YouTube blocks the IP address from fetching subtitles."""
    pass


class SubtitleSnippet(BaseModel):
    """Single subtitle snippet with timing."""

    start: float = Field(..., description="Start time in seconds")
    duration: float = Field(..., description="Duration in seconds")
    text: str = Field(..., description="Transcript text")


class VideoMetadata(BaseModel):
    """Metadata extracted from YouTube video."""

    video_id: str
    title: str
    url: str
    channel: str = "Unknown Channel"
    channel_url: Optional[str] = None
    upload_date: Optional[str] = None  # Format: YYYYMMDD
    duration: Optional[float] = None  # Duration in seconds
    description: Optional[str] = None


class VideoTranscriptData(BaseModel):
    """Container for video metadata and its transcript."""

    metadata: VideoMetadata
    subtitles: List[SubtitleSnippet]
    language: str
    is_generated: bool

    def formatted_transcript_text(self) -> str:
        """Format subtitles into timestamped lines for LLM processing."""
        lines = []
        for s in self.subtitles:
            minutes = int(s.start // 60)
            seconds = int(s.start % 60)
            timestamp = f"[{minutes:02d}:{seconds:02d}]"
            lines.append(f"{timestamp} {s.text}")
        return "\n".join(lines)


def normalize_channel_url(url: str) -> str:
    """Ensure channel URL points to /videos tab for chronological fetching."""
    url = url.strip()
    # Remove trailing slash
    cleaned = url.rstrip("/")
    # If it's already ending with /videos or /streams or /shorts, keep as is
    if cleaned.endswith(("/videos", "/streams", "/shorts")):
        return cleaned
    return f"{cleaned}/videos"


def fetch_channel_videos(channel_url: str, max_results: int = 50) -> List[VideoMetadata]:
    """Fetch recent video metadata from YouTube channel using yt-dlp flat extraction.

    Args:
        channel_url: Target YouTube channel URL.
        max_results: Maximum number of recent videos to extract (1 to 200).

    Returns:
        List of VideoMetadata objects.
    """
    target_url = normalize_channel_url(channel_url)
    ydl_opts = {
        "extract_flat": True,
        "playlist_items": f"1:{max_results}",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    results: List[VideoMetadata] = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(target_url, download=False)
        except Exception as e:
            logger.error(f"Failed to fetch channel videos from {target_url}: {e}")
            raise RuntimeError(f"チャンネル情報の取得に失敗しました: {e}") from e

        if not info:
            return results

        channel_title = info.get("channel") or info.get("uploader") or info.get("title") or "Unknown Channel"
        entries = info.get("entries") or []

        for entry in entries:
            if not entry:
                continue
            video_id = entry.get("id")
            if not video_id:
                continue

            title = entry.get("title") or f"Video {video_id}"
            url = entry.get("url")
            if not url or not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={video_id}"

            upload_date = entry.get("upload_date")
            duration = entry.get("duration")
            description = entry.get("description")
            entry_channel = entry.get("channel") or entry.get("uploader") or channel_title

            results.append(
                VideoMetadata(
                    video_id=video_id,
                    title=title,
                    url=url,
                    channel=entry_channel,
                    channel_url=channel_url,
                    upload_date=upload_date,
                    duration=duration,
                    description=description,
                )
            )

            if len(results) >= max_results:
                break

    return results


def _get_api_client():
    """Create a YouTubeTranscriptApi instance with browser headers."""
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    return YouTubeTranscriptApi(http_client=session)


def fetch_video_transcript(metadata: VideoMetadata, max_retries: int = 2) -> Optional[VideoTranscriptData]:
    """Fetch transcript for a given video with fallback language order.

    Fallback Priority:
    1. Japanese manual transcript ('ja')
    2. Japanese auto-generated transcript ('ja')
    3. English manual transcript ('en')
    4. English auto-generated transcript ('en')
    5. Any other available transcript

    Args:
        metadata: VideoMetadata object.
        max_retries: Number of retries on network/IP limit errors.

    Returns:
        VideoTranscriptData if transcript found, otherwise None.
    """
    import time
    video_id = metadata.video_id
    transcript_list = None

    for attempt in range(1, max_retries + 1):
        try:
            if hasattr(YouTubeTranscriptApi, "list_transcripts"):
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            else:
                api = _get_api_client()
                transcript_list = api.list(video_id)
            break
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            logger.info(f"No transcripts available for video {video_id} ({metadata.title}): {e}")
            return None
        except Exception as e:
            err_msg = str(e)
            is_blocked = "blocking requests from your IP" in err_msg or "429" in err_msg or "IpBlocked" in type(e).__name__
            if is_blocked:
                if attempt < max_retries:
                    logger.warning(f"YouTube rate limit/IP block on {video_id}. Retrying after 3 seconds (attempt {attempt}/{max_retries})...")
                    time.sleep(3.0)
                    continue
                logger.warning(f"YouTube rate limit/IP block confirmed on {video_id}. Triggering circuit breaker.")
                raise YouTubeIpBlockedException(f"YouTube rate limit/IP blocked on {video_id}: {e}")

            logger.warning(f"Failed to retrieve transcript list for {video_id} ({metadata.title}): {e}")
            return None

    if not transcript_list:
        return None

    selected_transcript = None
    language_code = "unknown"
    is_generated = False

    # 1. Japanese manual
    try:
        selected_transcript = transcript_list.find_manually_created_transcript(["ja", "ja-JP"])
        language_code = selected_transcript.language_code
        is_generated = False
    except Exception:
        pass

    # 2. Japanese auto-generated
    if not selected_transcript:
        try:
            selected_transcript = transcript_list.find_generated_transcript(["ja", "ja-JP"])
            language_code = selected_transcript.language_code
            is_generated = True
        except Exception:
            pass

    # 3. English manual
    if not selected_transcript:
        try:
            selected_transcript = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
            language_code = selected_transcript.language_code
            is_generated = False
        except Exception:
            pass

    # 4. English auto-generated
    if not selected_transcript:
        try:
            selected_transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
            language_code = selected_transcript.language_code
            is_generated = True
        except Exception:
            pass

    # 5. Fallback to any available transcript
    if not selected_transcript:
        try:
            # Pick first available transcript
            for t in transcript_list:
                selected_transcript = t
                language_code = t.language_code
                is_generated = t.is_generated
                break
        except Exception:
            pass

    if not selected_transcript:
        logger.warning(f"No suitable transcript could be selected for video {video_id}")
        return None

    raw_items = None
    for attempt in range(1, max_retries + 1):
        try:
            raw_items = selected_transcript.fetch()
            break
        except Exception as e:
            err_msg = str(e)
            is_blocked = "blocking requests from your IP" in err_msg or "429" in err_msg or "IpBlocked" in type(e).__name__
            if is_blocked:
                if attempt < max_retries:
                    logger.warning(f"YouTube rate limit on fetch for {video_id}. Retrying after 3 seconds...")
                    time.sleep(3.0)
                    continue
                logger.warning(f"YouTube rate limit on fetch confirmed for {video_id}. Triggering circuit breaker.")
                raise YouTubeIpBlockedException(f"YouTube rate limit/IP blocked on fetch for {video_id}: {e}")

            logger.warning(f"Failed to fetch content of selected transcript for {video_id}: {e}")
            return None

    if not raw_items:
        return None

    snippets: List[SubtitleSnippet] = []
    for item in raw_items:
        # Support both v1.x (FetchedTranscriptSnippet object) and v0.x (dict)
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            start = float(item.get("start", 0.0))
            duration = float(item.get("duration", 0.0))
        else:
            text = str(getattr(item, "text", "")).strip()
            start = float(getattr(item, "start", 0.0))
            duration = float(getattr(item, "duration", 0.0))

        if not text:
            continue
        snippets.append(SubtitleSnippet(start=start, duration=duration, text=text))

    if not snippets:
        logger.warning(f"Transcript for video {video_id} is empty.")
        return None

    return VideoTranscriptData(
        metadata=metadata,
        subtitles=snippets,
        language=language_code,
        is_generated=is_generated,
    )


def download_video_audio(metadata: VideoMetadata, target_dir: str = "/tmp") -> Optional[Any]:
    """Download audio-only stream for a video using yt-dlp at low bitrate (efficient for LLM).

    Args:
        metadata: VideoMetadata object.
        target_dir: Directory where the temporary audio will be stored.

    Returns:
        Path of the downloaded audio file, or None if failed.
    """
    import os
    from pathlib import Path

    video_id = metadata.video_id
    url = metadata.url or f"https://www.youtube.com/watch?v={video_id}"
    outtmpl = os.path.join(target_dir, f"ykh_audio_{video_id}.%(ext)s")

    ydl_opts = {
        "format": "ba[abr<=64]/ba/b",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the downloaded file
        for ext in ["webm", "m4a", "opus", "mp3", "ogg"]:
            candidate = Path(target_dir) / f"ykh_audio_{video_id}.{ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                logger.info(f"Successfully downloaded audio for {video_id}: {candidate} ({candidate.stat().st_size} bytes)")
                return candidate

        logger.warning(f"Audio file for {video_id} was not found after download.")
        return None
    except Exception as e:
        logger.error(f"Failed to download audio for {video_id}: {e}")
        return None
