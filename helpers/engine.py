"""
Orchestrator / Facade for the Recipe Ingestion & Database Engine.

Wires all sub-modules together and exposes a single, clean entry point
for external consumers (CLI, future API server, frontend adapter).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import DB_FILE_PATH, DATA_DIR, NOT_ADDED_FILE_PATH
from database import RecipeDatabase
from .ingester import TikTokIngester
from .nutrition import NutritionAnalyzer
from .query import QueryInterface
from .sync import SyncPipeline
from .tagger import AutoTagger

logger = logging.getLogger(__name__)


class RecipeEngine:
    """
    Top-level facade that initializes the full pipeline and provides
    convenience methods for ingestion, querying, and filtering.

    Usage:
        engine = RecipeEngine()
        engine.ingest_recipe("id_001", "Chicken Bowl", "...", "chicken, rice, broccoli")
        results = engine.search("chicken")
    """

    def __init__(
        self,
        db_path: str = DB_FILE_PATH,
        data_dir: str = DATA_DIR,
    ) -> None:
        # Initialize sub-modules
        self._database = RecipeDatabase(db_path)
        self._not_added_database = RecipeDatabase(NOT_ADDED_FILE_PATH)
        self._nutrition = NutritionAnalyzer(data_dir)
        self._tagger = AutoTagger()
        self._sync = SyncPipeline(self._database, self._not_added_database, self._nutrition, self._tagger)
        self._query = QueryInterface(self._database)
        self._ingester = TikTokIngester(self._sync)

        logger.info("RecipeEngine initialized — %d existing recipes loaded", self._database.count())

    # ── Ingestion ────────────────────────────────────

    def ingest_recipe(
        self,
        recipe_id: str,
        name: str,
        url: str,
        description: str,
        manual_tags: Optional[list[str]] = None,
    ) -> bool:
        """
        Ingest a single recipe through the full pipeline.

        Returns True if newly added, False if skipped (already exists).
        """
        return self._sync.process(recipe_id, name, url, description, manual_tags)

    def ingest_batch(self, items: list[dict[str, Any]]) -> dict[str, int]:
        """
        Ingest a batch of recipes.

        Each item must have keys: 'id', 'name', 'url', 'description'.
        Optional: 'manual_tags'.

        Returns: {"added": N, "skipped": M, "errors": K}
        """
        return self._sync.process_batch(items)

    def ingest_tiktok_playlist(self, playlist_url: str) -> dict[str, int]:
        """
        Scrape a TikTok playlist and ingest all discovered recipe videos.

        Requires Playwright and session cookies to be configured.
        Returns batch stats.
        """
        return self._ingester.ingest_playlist(playlist_url)

    def ingest_tiktok_playlist_detailed(self, playlist_url: str, delay_seconds: float = 5.0) -> dict[str, int]:
        """
        Scrape a TikTok playlist, scan for video URLs, and ingest each detailed recipe page
        slowly (delaying between requests) only if not already present in the database.
        """
        return self._ingester.ingest_playlist_detailed(playlist_url, delay_seconds)

    def ingest_tiktok_video(self, video_url: str) -> bool:
        """Ingest a single TikTok video by URL."""
        return self._ingester.ingest_single(video_url)

    # ── Queries ──────────────────────────────────────

    def search(self, query_string: str) -> dict[str, dict]:
        """Case-insensitive substring search across names and descriptions."""
        return self._query.search_by_keyword(query_string)

    def filter(self, tag_name: str) -> dict[str, dict]:
        """Filter recipes by exact tag match."""
        return self._query.filter_by_tag(tag_name)

    def get_all(self) -> dict[str, dict]:
        """Return the entire recipe collection."""
        return self._query.get_all_recipes()

    # ── Utility ──────────────────────────────────────

    @property
    def recipe_count(self) -> int:
        return self._database.count()

    def get_recipe(self, recipe_id: str) -> Optional[dict]:
        return self._database.get(recipe_id)

    def close(self) -> None:
        """Release resources (SQLite connections, etc.)."""
        self._nutrition.close()

    def __repr__(self) -> str:
        return f"<RecipeEngine recipes={self.recipe_count}>"
