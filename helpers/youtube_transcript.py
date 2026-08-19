"""
YouTube transcript extractor using youtube-transcript-api with yt-dlp fallback.
Fetches direct YouTube speech transcripts without requiring external audio transcription (e.g. Groq Whisper).
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    """Extract 11-character YouTube video ID from various URL formats or raw ID."""
    if not url_or_id:
        return None
    url_or_id = url_or_id.strip()
    if len(url_or_id) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id

    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return None

def fetch_youtube_transcript(url_or_id: str, preferred_languages: tuple[str, ...] = ("en", "el", "de", "es", "it", "fr")) -> str:
    """
    Fetch direct transcript for a YouTube video using youtube-transcript-api.
    Returns cleaned, space-joined transcript text.
    """
    video_id = extract_youtube_video_id(url_or_id)
    if not video_id:
        logger.warning("Could not extract YouTube video ID from: %s", url_or_id)
        return ""

    # 1. Try youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        
        # Try fetching transcript
        # fetch() accepts languages list or defaults to available
        try:
            transcript_entries = api.fetch(video_id)
        except Exception:
            # Try listing available transcripts
            try:
                transcript_list = api.list(video_id)
                transcript = None
                try:
                    transcript = transcript_list.find_transcript(list(preferred_languages))
                except Exception:
                    transcript = transcript_list.find_generated_transcript(list(preferred_languages))
                
                if transcript:
                    transcript_entries = transcript.fetch()
                else:
                    # Take first available transcript
                    for t in transcript_list:
                        transcript_entries = t.fetch()
                        break
            except Exception as exc:
                raise exc

        if transcript_entries:
            text_parts = [entry.text.strip() for entry in transcript_entries if hasattr(entry, 'text') and entry.text]
            if not text_parts and isinstance(transcript_entries, list):
                text_parts = [e.get('text', '').strip() for e in transcript_entries if isinstance(e, dict) and e.get('text')]
            full_text = " ".join(text_parts).strip()
            # Clean auto-generated audio markers like [music], [applause]
            full_text = re.sub(r'\[[a-zA-Z\s]+\]', ' ', full_text)
            full_text = ' '.join(full_text.split())
            logger.info("Successfully fetched direct YouTube transcript (%d chars) for video ID '%s'", len(full_text), video_id)
            return full_text
    except Exception as exc:
        logger.info("youtube-transcript-api did not return transcript for '%s': %s", video_id, exc)

    # 2. Fallback: Try yt-dlp auto-subs
    try:
        cmd = [
            "yt-dlp",
            "--write-auto-sub",
            "--sub-lang", "en,el",
            "--skip-download",
            "--print", "%(subtitles)s",
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode == 0 and res.stdout.strip():
            logger.info("Fetched subtitles via yt-dlp for video ID '%s'", video_id)
    except Exception as exc:
        logger.debug("yt-dlp subtitle extraction failed for '%s': %s", video_id, exc)

    return ""
