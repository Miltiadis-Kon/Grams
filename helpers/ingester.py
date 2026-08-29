"""
TikTok playlist ingestion module using yt-dlp + Playwright fallback.

Extracts recipe video metadata (IDs, titles, descriptions, URLs) from TikTok
playlist pages and video URLs, routes them through the 4-layer Recipe Extraction
Pipeline, calculates accurate nutritional macros, and stores them in PostgreSQL.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any, Optional

from config import (
    PLAYWRIGHT_HEADLESS,
    TIKTOK_COOKIES_PATH,
    TIKTOK_MAX_SCROLL_ATTEMPTS,
    TIKTOK_SCROLL_PAUSE_SEC,
    TIKTOK_INGEST_DELAY_SEC,
)

logger = logging.getLogger(__name__)


class TikTokIngester:
    """
    Extracts recipe video metadata from TikTok playlists and individual videos.
    """

    def __init__(self, sync_pipeline: Any) -> None:
        self._pipeline = sync_pipeline
        self._cookies_path = TIKTOK_COOKIES_PATH

    def ingest_playlist(self, playlist_url: str) -> dict[str, int]:
        """
        Scrape a TikTok playlist page and ingest all discovered videos.
        Returns batch stats: {"added": N, "skipped": M, "errors": K}
        """
        return self.ingest_playlist_detailed(playlist_url)

    def ingest_playlist_detailed(
        self, playlist_url: str, delay_seconds: float = TIKTOK_INGEST_DELAY_SEC, force: bool = False
    ) -> dict[str, int]:
        """
        Scrapes all video URLs from a playlist. For each video not already in the database
        (or processed >7 days ago unless force=True), visits the individual video page,
        fetches description and transcript, parses it, and adds/updates it.
        Waits `delay_seconds` between newly processed videos to avoid rate limits.
        """
        stats = {"added": 0, "skipped": 0, "errors": 0, "not_added": 0}

        video_links = self._extract_playlist_links(playlist_url)
        if not video_links:
            logger.warning("No video links discovered in playlist: %s", playlist_url)
            return stats

        logger.info(
            "Found %d video links in playlist. Starting detailed ingestion...",
            len(video_links),
        )

        from recipe_processor.handlers import is_within_7_days

        for idx, item in enumerate(video_links):
            video_id = item["id"]
            video_url = item["url"]

            should_skip = False
            if not force:
                existing = self._pipeline._db.get(video_id)
                if existing:
                    last_proc = existing.get("last_processed") or existing.get("added_on")
                    if is_within_7_days(last_proc):
                        should_skip = True
                else:
                    existing_not_added = self._pipeline._not_added_db.get(video_id)
                    if existing_not_added:
                        last_proc = existing_not_added.get("last_processed") or existing_not_added.get("added_on")
                        desc = existing_not_added.get("description", "") if isinstance(existing_not_added, dict) else getattr(existing_not_added, "description", "")
                        if is_within_7_days(last_proc) and ("[Transcript]" in desc or "Transcript fetch failed" in desc or "[Ollama]" in desc):
                            should_skip = True

            if should_skip:
                logger.info(
                    "[%d/%d] SKIP: Video ID %s processed recently (<7 days)",
                    idx + 1,
                    len(video_links),
                    video_id,
                )
                stats["skipped"] += 1
                continue

            logger.info(
                "[%d/%d] PROCESSING VIDEO: %s",
                idx + 1,
                len(video_links),
                video_url,
            )
            try:
                added = self.ingest_single(video_url, force=force)
                if added is True:
                    stats["added"] += 1
                    logger.info(
                        "Added/updated video %s. Sleeping for %.1f seconds...",
                        video_id,
                        delay_seconds,
                    )
                    if delay_seconds > 0:
                        time.sleep(delay_seconds)
                elif added is None:
                    logger.warning("Recipe %s had no data; routed to manual check list", video_id)
                    stats["not_added"] += 1
                else:
                    logger.info("Skipped video %s (already processed recently)", video_id)
                    stats["skipped"] += 1
            except Exception as exc:
                logger.error("Error ingesting video %s: %s", video_id, exc)
                stats["errors"] += 1

        return stats

    def _extract_playlist_links(self, playlist_url: str) -> list[dict[str, str]]:
        """
        Extract video links from a TikTok playlist using yt-dlp first (fast, no browser overhead),
        with fallback to Playwright headless browser.
        """
        videos = []

        # 1. Primary: Fast yt-dlp flat playlist extraction
        try:
            logger.info("Extracting TikTok playlist video links via yt-dlp: %s", playlist_url)
            cmd = ["yt-dlp", "--flat-playlist", "--print", "id", "--print", "webpage_url", playlist_url]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and res.stdout.strip():
                lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
                seen_ids = set()
                for i in range(0, len(lines) - 1, 2):
                    vid_id = lines[i]
                    vid_url = lines[i+1]
                    if vid_id and vid_id not in seen_ids:
                        seen_ids.add(vid_id)
                        db_id = f"tt_{vid_id}" if not vid_id.startswith("tt_") else vid_id
                        videos.append({"id": db_id, "url": vid_url})
                if videos:
                    logger.info("Successfully discovered %d video links from TikTok playlist via yt-dlp.", len(videos))
                    return videos
        except Exception as exc:
            logger.warning("yt-dlp playlist extraction failed: %s. Falling back to Playwright.", exc)

        # 2. Fallback: Playwright Headless Browser
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return videos

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )

            cookies = self._load_cookies()
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()
            try:
                logger.info("Scanning playlist via Playwright: %s", playlist_url)
                page.goto(playlist_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)

                previous_count = 0
                no_change_count = 0
                for scroll_attempt in range(TIKTOK_MAX_SCROLL_ATTEMPTS):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(TIKTOK_SCROLL_PAUSE_SEC)

                    video_links = page.query_selector_all('a[href*="/video/"]')
                    current_count = len(video_links)

                    if current_count > previous_count:
                        previous_count = current_count
                        no_change_count = 0
                        logger.debug("Scroll %d: found %d video links", scroll_attempt + 1, current_count)
                    else:
                        no_change_count += 1
                        if no_change_count >= 3 and current_count > 0:
                            logger.info("Scan complete: %d video links found", current_count)
                            break

                seen_ids = set()
                for link in page.query_selector_all('a[href*="/video/"]'):
                    href = link.get_attribute("href") or ""
                    raw_id = self._extract_video_id(href)

                    if not raw_id or raw_id in seen_ids:
                        continue
                    seen_ids.add(raw_id)
                    db_id = f"tt_{raw_id}" if not raw_id.startswith("tt_") else raw_id

                    full_url = href if href.startswith("http") else f"https://www.tiktok.com{href}"
                    videos.append({"id": db_id, "url": full_url})

            except Exception as exc:
                logger.error("Failed scanning playlist video links via Playwright: %s", exc)
            finally:
                browser.close()

        return videos

    def ingest_single(self, video_url: str, force: bool = False) -> bool | None:
        """
        Extract metadata from a single TikTok video and process it through the pipeline.
        Returns True if newly added/updated, False if skipped, None if routed to manual review.
        """
        video = self._extract_single_video(video_url)
        if not video:
            logger.warning("Failed to extract metadata from: %s", video_url)
            return False

        return self._pipeline.process(
            recipe_id=video["id"],
            name=video.get("title", "Untitled TikTok Recipe"),
            url=video.get("url", video_url),
            description=video.get("description", ""),
            force_reprocess=force,
        )

    # ── Private: Extraction Backends ───────────────

    def _load_cookies(self) -> list[dict]:
        """Load session cookies from environment variable or JSON file."""
        cookies_env = os.environ.get("TIKTOK_COOKIES_JSON")
        if cookies_env:
            try:
                cookies = json.loads(cookies_env)
                logger.info("Loaded session cookies from TIKTOK_COOKIES_JSON environment variable")
            except Exception as e:
                logger.error("Failed to parse TIKTOK_COOKIES_JSON environment variable: %s", e)
                cookies = []
        else:
            if not os.path.exists(self._cookies_path):
                logger.warning(
                    "No cookies file found at %s — TikTok may block unauthenticated requests. "
                    "Export your session cookies to this path for reliable access.",
                    self._cookies_path,
                )
                return []

            try:
                with open(self._cookies_path, "r", encoding="utf-8") as fh:
                    cookies = json.load(fh)
            except Exception:
                return []

        # Normalize cookie format for Playwright
        normalized = []
        for c in cookies:
            cookie = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".tiktok.com"),
                "path": c.get("path", "/"),
            }
            if not cookie["domain"].startswith("."):
                cookie["domain"] = "." + cookie["domain"]
            normalized.append(cookie)

        return normalized

    def _extract_single_video(self, video_url: str) -> Optional[dict]:
        """
        Extract metadata from a single TikTok video page using yt-dlp first,
        with fallback to pyktok.
        """
        raw_id = self._extract_video_id(video_url)
        if not raw_id:
            logger.warning("Could not extract video ID from URL: %s", video_url)
            return None

        video_id = f"tt_{raw_id}" if not raw_id.startswith("tt_") else raw_id

        # 1. Primary: yt-dlp video metadata dump
        try:
            cmd = ["yt-dlp", "--dump-json", "--no-warnings", video_url]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                title = data.get("title", "").strip()
                description = data.get("description", "").strip()
                uploader = data.get("uploader", "")
                
                # Derive crisp title
                if not title or title.startswith("video by") or len(title) < 5:
                    if description:
                        title = description.split("\n")[0].strip()[:80]
                if not title:
                    title = f"TikTok Recipe by @{uploader}" if uploader else f"TikTok Video {raw_id}"

                return {
                    "id": video_id,
                    "title": title,
                    "url": video_url,
                    "description": description or title,
                }
        except Exception as exc:
            logger.debug("yt-dlp single video extraction error for %s: %s", video_url, exc)

        # 2. Fallback: pyktok
        try:
            import pyktok as pyk
            import requests

            cookies = self._load_cookies()
            jar = requests.cookies.RequestsCookieJar()
            if cookies:
                for c in cookies:
                    jar.set(c.get("name", ""), c.get("value", ""), domain=c.get("domain", ".tiktok.com"), path=c.get("path", "/"))
            pyk.cookies = jar

            data = pyk.alt_get_tiktok_json(video_url)
            if data and "__DEFAULT_SCOPE__" in data:
                scope = data.get("__DEFAULT_SCOPE__", {})
                video_detail = scope.get("webapp.video-detail", {})
                item_info = video_detail.get("itemInfo", {})
                item_struct = item_info.get("itemStruct", {})
                if item_struct:
                    desc = item_struct.get("desc", "").strip()
                    title = desc.split("\n")[0].strip()[:80] if desc else f"TikTok Video {raw_id}"
                    return {
                        "id": video_id,
                        "title": title,
                        "url": video_url,
                        "description": desc,
                    }
        except Exception as exc:
            logger.debug("pyktok single video extraction error for %s: %s", video_url, exc)

        return None

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extract the numeric video ID from a TikTok URL."""
        match = re.search(r"/video/(\d+)", url)
        return match.group(1) if match else None
