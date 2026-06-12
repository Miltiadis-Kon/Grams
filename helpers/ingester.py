"""
TikTok playlist ingestion module using Playwright (headless) + session cookies.

Extracts video metadata (IDs, titles, descriptions, URLs) from TikTok
playlist pages by rendering them in a headless Chromium browser with
authenticated session cookies for reliable access.

For local development: uses personal session cookies from a JSON file.
For production scale: designed to be swapped out for a cloud client (e.g. Apify).
"""

from __future__ import annotations

import json
import logging
import os
import re
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
    Extracts recipe video metadata from TikTok playlists using Playwright.

    Usage:
        ingester = TikTokIngester(sync_pipeline)
        stats = ingester.ingest_playlist("https://vm.tiktok.com/...")

    Cookie Setup:
        Export your TikTok session cookies to 'tiktok_cookies.json' in the
        project root. Each cookie should be a dict with at minimum:
        {"name": "...", "value": "...", "domain": ".tiktok.com", "path": "/"}
    """

    def __init__(self, sync_pipeline: Any) -> None:
        self._pipeline = sync_pipeline
        self._cookies_path = TIKTOK_COOKIES_PATH

    def ingest_playlist(self, playlist_url: str) -> dict[str, int]:
        """
        Scrape a TikTok playlist page and ingest all discovered videos.

        Returns batch stats: {"added": N, "skipped": M, "errors": K}
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Install it with:\n"
                "  pip install playwright\n"
                "  playwright install chromium\n"
                "Then export your TikTok session cookies to "
                f"'{self._cookies_path}'"
            )

        videos = self._extract_playlist_metadata(playlist_url)

        if not videos:
            logger.warning("No videos extracted from playlist: %s", playlist_url)
            return {"added": 0, "skipped": 0, "errors": 0}

        # Convert to the batch format expected by SyncPipeline
        items = []
        for video in videos:
            items.append({
                "id": video["id"],
                "name": video.get("title", "Untitled TikTok Recipe"),
                "url": video.get("url", playlist_url),
                "description": video.get("description", ""),
            })

        return self._pipeline.process_batch(items)

    def ingest_playlist_detailed(
        self, playlist_url: str, delay_seconds: float = TIKTOK_INGEST_DELAY_SEC
    ) -> dict[str, int]:
        """
        Scrapes all video URLs from a playlist. For each video not already in the database,
        visits the individual video page to fetch the full description, parses it, and adds it.
        Waits `delay_seconds` between newly processed videos to avoid rate limits.
        """
        stats = {"added": 0, "skipped": 0, "errors": 0}

        video_links = self._extract_playlist_links(playlist_url)
        if not video_links:
            logger.warning("No video links discovered in playlist: %s", playlist_url)
            return stats

        logger.info(
            "Found %d video links in playlist. Starting detailed slow ingestion...",
            len(video_links),
        )

        for idx, item in enumerate(video_links):
            video_id = item["id"]
            video_url = item["url"]

            # O(1) skip check before hitting the network for this video
            if self._pipeline._db.exists(video_id):
                logger.info(
                    "[%d/%d] SKIP: Video ID %s already exists in database",
                    idx + 1,
                    len(video_links),
                    video_id,
                )
                stats["skipped"] += 1
                continue

            logger.info(
                "[%d/%d] PROCESSING NEW VIDEO: %s",
                idx + 1,
                len(video_links),
                video_url,
            )
            try:
                added = self.ingest_single(video_url)
                if added:
                    stats["added"] += 1
                    logger.info(
                        "Added video %s. Sleeping for %.1f seconds...",
                        video_id,
                        delay_seconds,
                    )
                    time.sleep(delay_seconds)
                else:
                    logger.warning("Skipped / failed to add video %s", video_id)
                    stats["skipped"] += 1
            except Exception as exc:
                logger.error("Error ingesting video %s: %s", video_id, exc)
                stats["errors"] += 1

        return stats

    def _extract_playlist_links(self, playlist_url: str) -> list[dict[str, str]]:
        """
        Loads the playlist page using Playwright, scrolls to load all videos,
        and extracts only their IDs and URLs.
        """
        from playwright.sync_api import sync_playwright

        videos = []
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
                logger.info("Scanning playlist for video links: %s", playlist_url)
                page.goto(playlist_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                previous_count = 0
                for scroll_attempt in range(TIKTOK_MAX_SCROLL_ATTEMPTS):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(TIKTOK_SCROLL_PAUSE_SEC)

                    video_links = page.query_selector_all('a[href*="/video/"]')
                    current_count = len(video_links)

                    if current_count > previous_count:
                        previous_count = current_count
                        logger.debug(
                            "Scroll %d: found %d video links",
                            scroll_attempt + 1,
                            current_count,
                        )
                    else:
                        logger.info("Scan complete: %d video links found", current_count)
                        break

                seen_ids = set()
                for link in page.query_selector_all('a[href*="/video/"]'):
                    href = link.get_attribute("href") or ""
                    video_id = self._extract_video_id(href)

                    if not video_id or video_id in seen_ids:
                        continue
                    seen_ids.add(video_id)

                    full_url = href if href.startswith("http") else f"https://www.tiktok.com{href}"
                    videos.append({"id": video_id, "url": full_url})

            except Exception as exc:
                logger.error("Failed scanning playlist video links: %s", exc)
            finally:
                browser.close()

        return videos

    def ingest_single(self, video_url: str) -> bool:
        """
        Extract metadata from a single TikTok video and process it.

        Returns True if the recipe was newly added, False if skipped.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        video = self._extract_single_video(video_url)
        if not video:
            logger.warning("Failed to extract metadata from: %s", video_url)
            return False

        return self._pipeline.process(
            recipe_id=video["id"],
            name=video.get("title", "Untitled"),
            url=video.get("url", video_url),
            description=video.get("description", ""),
        )

    # ── Private: Playwright Extraction ───────────────

    def _load_cookies(self) -> list[dict]:
        """Load session cookies from JSON file."""
        if not os.path.exists(self._cookies_path):
            logger.warning(
                "No cookies file found at %s — TikTok may block unauthenticated requests. "
                "Export your session cookies to this path for reliable access.",
                self._cookies_path,
            )
            return []

        with open(self._cookies_path, "r", encoding="utf-8") as fh:
            cookies = json.load(fh)

        # Normalize cookie format for Playwright
        normalized = []
        for c in cookies:
            cookie = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".tiktok.com"),
                "path": c.get("path", "/"),
            }
            # Playwright requires either url or domain+path
            if not cookie["domain"].startswith("."):
                cookie["domain"] = "." + cookie["domain"]
            normalized.append(cookie)

        logger.info("Loaded %d session cookies from %s", len(normalized), self._cookies_path)
        return normalized

    def _extract_playlist_metadata(self, playlist_url: str) -> list[dict]:
        """
        Use Playwright to load a TikTok playlist page and extract video metadata.

        Scrolls to load dynamically-rendered content and parses video links
        and descriptions from the page DOM.
        """
        from playwright.sync_api import sync_playwright

        videos = []

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

            # Inject session cookies
            cookies = self._load_cookies()
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()

            try:
                logger.info("Navigating to playlist: %s", playlist_url)
                page.goto(playlist_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)  # Let JS hydrate

                # Scroll to load all playlist items
                previous_count = 0
                for scroll_attempt in range(TIKTOK_MAX_SCROLL_ATTEMPTS):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(TIKTOK_SCROLL_PAUSE_SEC)

                    # Count video links currently on page
                    video_links = page.query_selector_all('a[href*="/video/"]')
                    current_count = len(video_links)

                    if current_count > previous_count:
                        previous_count = current_count
                        logger.debug(
                            "Scroll %d: found %d videos", scroll_attempt + 1, current_count
                        )
                    else:
                        # No new content loaded — we've reached the bottom
                        logger.info(
                            "Scroll complete after %d attempts: %d videos found",
                            scroll_attempt + 1, current_count,
                        )
                        break

                # Extract metadata from each video link
                video_links = page.query_selector_all('a[href*="/video/"]')
                seen_ids: set[str] = set()

                for link in video_links:
                    href = link.get_attribute("href") or ""
                    video_id = self._extract_video_id(href)

                    if not video_id or video_id in seen_ids:
                        continue
                    seen_ids.add(video_id)

                    # Try to extract title/description from nearby elements
                    description = ""
                    img = link.query_selector("img")
                    if img:
                        description = img.get_attribute("alt") or ""

                    if not description:
                        parent = link.query_selector("xpath=..")
                        if parent:
                            desc_el = parent.query_selector(
                                '[class*="desc"], [class*="title"], [class*="caption"], [data-e2e="collection-item-desc"]'
                            )
                            if desc_el:
                                description = desc_el.inner_text() or desc_el.get_attribute("aria-label") or ""

                    description = description.strip()

                    # Set a friendly title from the description first line, or fallback
                    title = ""
                    if description:
                        title = description.split("\n")[0].strip()[:80]
                    if not title:
                        title = link.get_attribute("title") or link.get_attribute("aria-label") or ""
                    if not title:
                        title = f"TikTok Video {video_id}"

                    full_url = href if href.startswith("http") else f"https://www.tiktok.com{href}"

                    videos.append({
                        "id": video_id,
                        "title": title.strip(),
                        "url": full_url,
                        "description": (description or title).strip(),
                    })

                logger.info("Extracted %d unique videos from playlist", len(videos))

            except Exception as exc:
                logger.error("Playwright extraction failed: %s", exc)
            finally:
                browser.close()

        return videos

    def _extract_single_video(self, video_url: str) -> Optional[dict]:
        """Extract metadata from a single TikTok video page."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            cookies = self._load_cookies()
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()

            try:
                page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                video_id = self._extract_video_id(video_url)
                if not video_id:
                    return None

                # Try to get description from embedded JSON state
                try:
                    sigi = page.query_selector('script#SIGI_STATE, script#__UNIVERSAL_DATA_FOR_REHYDRATION__')
                    if sigi:
                        data = json.loads(sigi.inner_text())
                        # Navigate the typical TikTok state structure
                        item_module = data.get("ItemModule", {})
                        video_data = item_module.get(video_id, {})
                        return {
                            "id": video_id,
                            "title": video_data.get("desc", f"TikTok Video {video_id}"),
                            "url": video_url,
                            "description": video_data.get("desc", ""),
                        }
                except Exception:
                    pass

                # Fallback: extract from visible DOM
                title = page.title() or f"TikTok Video {video_id}"
                desc_el = page.query_selector(
                    '[class*="desc"], [data-e2e="browse-video-desc"], h1'
                )
                description = desc_el.inner_text() if desc_el else title

                return {
                    "id": video_id,
                    "title": title.strip(),
                    "url": video_url,
                    "description": description.strip(),
                }

            except Exception as exc:
                logger.error("Single video extraction failed for %s: %s", video_url, exc)
                return None
            finally:
                browser.close()

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extract the numeric video ID from a TikTok URL."""
        match = re.search(r"/video/(\d+)", url)
        return match.group(1) if match else None
