"""
Incremental sync pipeline with delta handling.

Before calling the nutrition analyzer or tagger, cross-references each
incoming recipe ID against the existing database. If the ID already exists,
all processing is skipped entirely — achieving O(1) deduplication.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from database import RecipeDatabase
from models import MacroNutrients, Recipe
from nutrition import NutritionAnalyzer
from tagger import AutoTagger

logger = logging.getLogger(__name__)


class SyncPipeline:
    """
    Orchestrates the ingestion flow for individual recipe payloads:
    1. Delta check (skip if exists)
    2. Nutritional analysis
    3. Auto-tagging
    4. Database insertion
    """

    def __init__(
        self,
        database: RecipeDatabase,
        nutrition_analyzer: NutritionAnalyzer,
        tagger: AutoTagger,
    ) -> None:
        self._db = database
        self._nutrition = nutrition_analyzer
        self._tagger = tagger

    def process(
        self,
        recipe_id: str,
        name: str,
        url: str,
        description: str,
        manual_tags: Optional[list[str]] = None,
    ) -> bool:
        """
        Process a single recipe payload through the full pipeline.

        Returns True if the recipe was newly added, False if skipped.
        """
        # ── Step 1: Delta check ──────────────────────
        if self._db.exists(recipe_id):
            logger.info("SKIP: Recipe '%s' (%s) already in database", recipe_id, name)
            return False

        # ── Step 2: Nutritional analysis ─────────────
        try:
            macros, ingredients = self._nutrition.analyze(description)
        except Exception as exc:
            logger.error(
                "Nutrition analysis failed for '%s': %s — using empty macros and ingredients",
                recipe_id, exc,
            )
            macros = MacroNutrients()
            ingredients = []

        # ── Step 3: Build Recipe object ──────────────
        recipe = Recipe(
            name=name,
            url=url,
            description=description,
            macros=macros,
            ingredients=ingredients,
            added_on=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # ── Step 4: Auto-tag ─────────────────────────
        recipe.tags = self._tagger.tag(recipe, manual_tags)

        # ── Step 5: Persist ──────────────────────────
        self._db.insert(recipe_id, recipe)
        logger.info("ADDED: Recipe '%s' (%s) — %d tags", recipe_id, name, len(recipe.tags))
        return True

    def process_batch(self, items: list[dict[str, Any]]) -> dict[str, int]:
        """
        Process a batch of recipe payloads.

        Each item must have keys: 'id', 'name', 'url', 'description'.
        Optional key: 'manual_tags' (list of strings).

        Returns stats: {"added": N, "skipped": M, "errors": K}
        """
        stats = {"added": 0, "skipped": 0, "errors": 0}

        for item in items:
            try:
                recipe_id = item["id"]
                name = item.get("name", "Untitled")
                url = item.get("url", "")
                description = item.get("description", "")
                manual_tags = item.get("manual_tags")

                added = self.process(recipe_id, name, url, description, manual_tags)
                if added:
                    stats["added"] += 1
                else:
                    stats["skipped"] += 1

            except KeyError as exc:
                logger.error("Batch item missing required field: %s — item: %s", exc, item)
                stats["errors"] += 1
            except Exception as exc:
                logger.error("Unexpected error processing item: %s — %s", item, exc)
                stats["errors"] += 1

        logger.info(
            "Batch complete: %d added, %d skipped, %d errors",
            stats["added"], stats["skipped"], stats["errors"],
        )
        return stats
