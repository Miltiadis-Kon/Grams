"""
YouTube playlist and video ingestion module.
Extracts video metadata and direct YouTube transcripts (without Whisper/Groq transcription)
and passes them through the RecipePipeline.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from typing import Any, Optional

from helpers.youtube_transcript import extract_youtube_video_id, fetch_youtube_transcript
from recipe_processor.pipeline import RecipePipeline

logger = logging.getLogger(__name__)


class YouTubeIngester:
    """
    Ingests YouTube videos and playlists into the recipe database.
    """

    def __init__(self, pipeline: RecipePipeline) -> None:
        self._pipeline = pipeline

    def extract_playlist_videos(self, playlist_url: str) -> list[dict[str, str]]:
        """
        Extract all video URLs and metadata from a YouTube playlist using yt-dlp flat playlist extraction.
        """
        logger.info("Extracting YouTube playlist entries from: %s", playlist_url)
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "-J",
            playlist_url,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
            data = json.loads(res.stdout)
            entries = data.get("entries", [])
            
            videos = []
            seen_ids = set()
            for entry in entries:
                v_id = entry.get("id") or extract_youtube_video_id(entry.get("url", ""))
                if not v_id or v_id in seen_ids:
                    continue
                seen_ids.add(v_id)
                
                title = entry.get("title", f"YouTube Video {v_id}")
                url = f"https://www.youtube.com/watch?v={v_id}"
                videos.append({
                    "id": f"yt_{v_id}",
                    "raw_id": v_id,
                    "title": title,
                    "url": url,
                    "description": entry.get("description", ""),
                })
            
            logger.info("Found %d videos in YouTube playlist '%s'", len(videos), data.get("title", playlist_url))
            return videos
        except Exception as exc:
            logger.error("Failed to extract YouTube playlist '%s': %s", playlist_url, exc)
            return []

    def extract_video_info(self, video_url: str) -> Optional[dict[str, Any]]:
        """
        Extract full metadata for a single YouTube video using yt-dlp.
        """
        v_id = extract_youtube_video_id(video_url)
        if not v_id:
            logger.error("Invalid YouTube URL: %s", video_url)
            return None

        canonical_url = f"https://www.youtube.com/watch?v={v_id}"
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            canonical_url,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
            data = json.loads(res.stdout)
            return {
                "id": f"yt_{v_id}",
                "raw_id": v_id,
                "title": data.get("title", f"YouTube Video {v_id}"),
                "url": canonical_url,
                "description": data.get("description", ""),
            }
        except Exception as exc:
            logger.warning("yt-dlp metadata extraction failed for '%s': %s", video_url, exc)
            return {
                "id": f"yt_{v_id}",
                "raw_id": v_id,
                "title": f"YouTube Video {v_id}",
                "url": canonical_url,
                "description": "",
            }

    def ingest_single(self, video_url: str, force: bool = False) -> Optional[bool]:
        """
        Extract metadata and direct transcript from a single YouTube video and process it.
        Returns:
            True: Added or updated in recipes
            False: Skipped (e.g. processed recently)
            None: Routed to manual review (not_added_recipes)
        """
        video_info = self.extract_video_info(video_url)
        if not video_info:
            return False

        # Fetch direct YouTube transcript without Whisper
        transcript_text = fetch_youtube_transcript(video_info["raw_id"])

        logger.info("Processing YouTube recipe '%s' (%s)...", video_info["id"], video_info["title"])
        return self._pipeline.process(
            recipe_id=video_info["id"],
            name=video_info["title"],
            url=video_info["url"],
            description=video_info["description"],
            transcript=transcript_text,
            force_reprocess=force,
        )

    def ingest_playlist(
        self,
        playlist_url: str,
        force: bool = False,
        max_videos: Optional[int] = None,
        delay_sec: float = 0.5,
    ) -> dict[str, int]:
        """
        Ingest an entire YouTube playlist.
        """
        videos = self.extract_playlist_videos(playlist_url)
        if max_videos and max_videos > 0:
            videos = videos[:max_videos]

        stats = {"total": len(videos), "added": 0, "skipped": 0, "not_added": 0, "errors": 0}
        logger.info("Starting ingestion of %d YouTube videos from playlist...", len(videos))

        for idx, video in enumerate(videos, start=1):
            logger.info("--- [%d/%d] Ingesting YouTube Video: %s | %s ---", idx, len(videos), video["id"], video["title"])
            try:
                # Fetch full metadata if description was missing in flat extraction
                desc = video.get("description", "")
                if not desc:
                    full_info = self.extract_video_info(video["url"])
                    if full_info:
                        desc = full_info.get("description", "")
                        video["description"] = desc
                        if full_info.get("title"):
                            video["title"] = full_info.get("title")

                # Fetch direct YouTube transcript (no Groq Whisper needed)
                transcript_text = fetch_youtube_transcript(video["raw_id"])

                status = self._pipeline.process(
                    recipe_id=video["id"],
                    name=video["title"],
                    url=video["url"],
                    description=desc,
                    transcript=transcript_text,
                    force_reprocess=force,
                )

                if status is True:
                    stats["added"] += 1
                elif status is False:
                    stats["skipped"] += 1
                elif status is None:
                    stats["not_added"] += 1

                if delay_sec > 0 and idx < len(videos):
                    time.sleep(delay_sec)

            except Exception as exc:
                logger.error("Error processing YouTube video '%s': %s", video["id"], exc)
                stats["errors"] += 1

        logger.info("YouTube playlist ingestion complete! Summary: %s", stats)
        return stats
