"""
Incremental sync pipeline with delta handling.

Before calling the nutrition analyzer or tagger, cross-references each
incoming recipe ID against the existing database. If the ID already exists,
all processing is skipped entirely — achieving O(1) deduplication.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

from database import RecipeDatabase, MacroNutrients, Recipe
from .nutrition import NutritionAnalyzer
from .tagger import AutoTagger

logger = logging.getLogger(__name__)


class SyncPipeline:
    """
    Orchestrates the ingestion flow for individual recipe payloads:
    1. Delta check (skip if exists in main or not-added database)
    2. Nutritional analysis
    3. Supadata API fallback if no macros parsed
    4. Auto-tagging
    5. Database insertion (route to main if filled, otherwise to not-added)
    """

    def __init__(
        self,
        database: RecipeDatabase,
        not_added_database: RecipeDatabase,
        nutrition_analyzer: NutritionAnalyzer,
        tagger: AutoTagger,
    ) -> None:
        self._db = database
        self._not_added_db = not_added_database
        self._nutrition = nutrition_analyzer
        self._tagger = tagger

    @staticmethod
    def _translate_description_if_needed(text: str) -> str:
        """
        Detect if the text is predominantly non-English (e.g. Greek) and, if so,
        translate the entire block to English so the ingredient parser can work on it.
        The original text is preserved and the translation is appended.
        """
        if not text:
            return text

        # Detect Greek (or other non-Latin) characters
        has_greek = bool(re.search(r'[\u0370-\u03ff\u1f00-\u1fff]', text))
        # Also detect if the bulk of alphabetic chars are non-ASCII (covers Italian, etc.)
        alpha_chars = [c for c in text if c.isalpha()]
        non_ascii_ratio = sum(1 for c in alpha_chars if ord(c) > 127) / max(len(alpha_chars), 1)

        if not has_greek and non_ascii_ratio < 0.3:
            return text  # Already mostly English, no translation needed

        try:
            from translate import Translator
            # Chunk into pieces ≤ 500 chars to stay within MyMemory free limit
            MAX_CHUNK = 450
            chunks = []
            # Split by sentences first to avoid breaking mid-word
            sentences = re.split(r'(?<=[.!?])\s+', text)
            current = ""
            for sentence in sentences:
                if len(current) + len(sentence) + 1 > MAX_CHUNK:
                    if current:
                        chunks.append(current.strip())
                    current = sentence
                else:
                    current = f"{current} {sentence}".strip() if current else sentence
            if current:
                chunks.append(current.strip())

            translator = Translator(to_lang="en")
            translated_parts = []
            for chunk in chunks:
                try:
                    translated = translator.translate(chunk)
                    # MyMemory returns "MYMEMORY WARNING" when limit is hit
                    if translated and "MYMEMORY WARNING" not in translated:
                        translated_parts.append(translated)
                    else:
                        translated_parts.append(chunk)  # keep original on error
                except Exception:
                    translated_parts.append(chunk)

            translated_text = " ".join(translated_parts)
            logger.info("Translated description to English (%d chars)", len(translated_text))
            # Append the English translation after the original so both are stored
            return f"{text}\n\n[English Translation]\n{translated_text}"
        except Exception as exc:
            logger.warning("Description translation failed: %s", exc)
            return text

    # ── Processing ────────────────────────────────────────────────────────────

    def process(
        self,
        recipe_id: str,
        name: str,
        url: str,
        description: str,
        manual_tags: Optional[list[str]] = None,
    ) -> bool | None:
        """
        Process a single recipe payload through the full pipeline.

        Returns:
          True: Recipe was newly added to recipes_db.json
          False: Recipe already processed (skipped)
          None: Recipe had no data and was saved to not_added_recipes.json for manual check
        """
        # ── Step 1: Delta check ──────────────────────
        if self._db.exists(recipe_id):
            logger.info("SKIP: Recipe '%s' (%s) already in main database", recipe_id, name)
            return False

        if self._not_added_db.exists(recipe_id):
            existing = self._not_added_db.get(recipe_id)
            desc = ""
            if existing:
                if isinstance(existing, dict):
                    desc = existing.get("description", "")
                else:
                    desc = getattr(existing, "description", "")
            if "[Transcript]" in desc or "Transcript fetch failed" in desc:
                logger.info("SKIP: Recipe '%s' (%s) already processed and Supadata fallback attempted", recipe_id, name)
                return False
            else:
                logger.info("RE-PROCESSING: Recipe '%s' (%s) from manual check list to attempt Supadata fallback", recipe_id, name)

        # ── Step 2: Nutritional analysis ─────────────
        # First, translate the description if it is non-English
        description = self._translate_description_if_needed(description)

        macros = MacroNutrients()
        ingredients = []
        try:
            macros, ingredients = self._nutrition.analyze(description)
        except Exception as exc:
            logger.error(
                "Nutrition analysis failed for '%s': %s",
                recipe_id, exc,
            )

        # Check if we retrieved no data
        is_empty = (
            macros.protein == 0.0 and
            macros.carbs == 0.0 and
            macros.fats == 0.0 and
            macros.calories == 0
        )

        if is_empty:
            logger.info("No nutritional data retrieved for '%s'. Attempting Supadata transcript fallback...", recipe_id)
            try:
                import config
                supadata_key = getattr(config, "SUPADATA_API_KEY", None)
                if not supadata_key:
                    raise ValueError("SUPADATA_API_KEY is not defined in config.py")
                from supadata import Supadata

                client = Supadata(api_key=supadata_key)
                transcript = client.transcript(url=url, text=True, mode="auto")
                if hasattr(transcript, 'content') and transcript.content:
                    transcript_text = transcript.content.strip()
                    logger.info("Successfully fetched transcript via Supadata: %s...", transcript_text[:100])

                    # Always accumulate the full text into description so it is stored
                    if description:
                        description = f"{description}\n\n[Transcript]\n{transcript_text}"
                    else:
                        description = transcript_text

                    # Detect if description contains non-English (e.g. Greek) and translate
                    description = self._translate_description_if_needed(description)

                    # Re-analyze with the full, possibly translated description
                    macros, ingredients = self._nutrition.analyze(description)
                else:
                    logger.warning("Supadata transcript returned empty content for url: %s", url)
                    if description:
                        description = f"{description}\n\n[Transcript fetch failed: empty content]"
                    else:
                        description = "[Transcript fetch failed: empty content]"
            except Exception as supadata_exc:
                logger.error("Supadata transcript fetch failed: %s", supadata_exc)
                if description:
                    description = f"{description}\n\n[Transcript fetch failed: {supadata_exc}]"
                else:
                    description = f"[Transcript fetch failed: {supadata_exc}]"

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

        # ── Step 5: Persist / Route ──────────────────
        is_filled = not (
            recipe.macros.protein == 0.0 and
            recipe.macros.carbs == 0.0 and
            recipe.macros.fats == 0.0 and
            recipe.macros.calories == 0
        )

        if is_filled:
            # If it was in the not-added database, remove it first
            if self._not_added_db.exists(recipe_id):
                self._not_added_db.delete(recipe_id)
            self._db.insert(recipe_id, recipe)
            logger.info("ADDED: Recipe '%s' (%s) — %d tags", recipe_id, name, len(recipe.tags))
            return True
        else:
            # Delete first to prevent "already exists" error on insert
            if self._not_added_db.exists(recipe_id):
                self._not_added_db.delete(recipe_id)
            self._not_added_db.insert(recipe_id, recipe)
            logger.info("NOT ADDED (Unfilled): Recipe '%s' (%s) saved/updated in manual check list", recipe_id, name)
            return None

    def process_batch(self, items: list[dict[str, Any]]) -> dict[str, int]:
        """
        Process a batch of recipe payloads.

        Each item must have keys: 'id', 'name', 'url', 'description'.
        Optional key: 'manual_tags' (list of strings).

        Returns stats: {"added": N, "skipped": M, "errors": K, "not_added": L}
        """
        stats = {"added": 0, "skipped": 0, "errors": 0, "not_added": 0}

        for item in items:
            try:
                recipe_id = item["id"]
                name = item.get("name", "Untitled")
                url = item.get("url", "")
                description = item.get("description", "")
                manual_tags = item.get("manual_tags")

                added = self.process(recipe_id, name, url, description, manual_tags)
                if added is True:
                    stats["added"] += 1
                elif added is None:
                    stats["not_added"] += 1
                else:
                    stats["skipped"] += 1

            except KeyError as exc:
                logger.error("Batch item missing required field: %s — item: %s", exc, item)
                stats["errors"] += 1
            except Exception as exc:
                logger.error("Unexpected error processing item: %s — %s", item, exc)
                stats["errors"] += 1

        logger.info(
            "Batch complete: %d added, %d skipped, %d not added, %d errors",
            stats["added"], stats["skipped"], stats["not_added"], stats["errors"],
        )
        return stats
