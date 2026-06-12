"""
Auto-tagging engine for the Recipe Ingestion & Database Engine.

Assigns tags based on:
1. Numerical macro thresholds (High-Protein, Keto-Friendly, Low-Calorie)
2. Keyword scanning against recipe name and description
3. Optional manual user-defined tags (merged via set union)
"""

from __future__ import annotations

import logging
from typing import Optional

from config import (
    KEYWORD_TAG_MAP,
    TAG_HIGH_PROTEIN_MIN,
    TAG_KETO_CARBS_MAX,
    TAG_KETO_FATS_MIN,
    TAG_LOW_CALORIE_MAX,
)
from database import Recipe

logger = logging.getLogger(__name__)


class AutoTagger:
    """
    Programmatic tag engine that analyzes recipe macros and text fields
    to produce a deduplicated, sorted list of descriptive tags.
    """

    def __init__(
        self,
        keyword_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._keyword_map = keyword_map or KEYWORD_TAG_MAP

    def tag(
        self,
        recipe: Recipe,
        manual_tags: Optional[list[str]] = None,
    ) -> list[str]:
        """
        Generate tags for a recipe by combining:
        1. Macro-threshold tags
        2. Keyword-scanned tags
        3. Manual user-provided tags

        Returns a deduplicated, sorted list.
        """
        auto_tags: set[str] = set()

        # ── 1. Threshold-based tags ──────────────────
        macros = recipe.macros

        if macros.protein >= TAG_HIGH_PROTEIN_MIN:
            auto_tags.add("High-Protein")

        if macros.carbs <= TAG_KETO_CARBS_MAX and macros.fats >= TAG_KETO_FATS_MIN:
            auto_tags.add("Keto-Friendly")

        if macros.calories <= TAG_LOW_CALORIE_MAX and macros.calories > 0:
            auto_tags.add("Low-Calorie")

        # ── 2. Keyword scanning ──────────────────────
        searchable_text = f"{recipe.name} {recipe.description}".lower()

        for keyword, tag_value in self._keyword_map.items():
            if keyword.lower() in searchable_text:
                auto_tags.add(tag_value)

        # ── 3. Set union with manual tags ────────────
        if manual_tags:
            auto_tags.update(manual_tags)

        result = sorted(auto_tags)
        logger.debug("Tags for '%s': %s", recipe.name, result)
        return result
