"""
External data query interface for the Recipe Ingestion & Database Engine.

Exposes clean public methods that act as backend API endpoints for a future UI.
All queries operate on the in-memory dict for O(1) or O(n) performance.
"""

from __future__ import annotations

import logging

from database import RecipeDatabase

logger = logging.getLogger(__name__)


class QueryInterface:
    """
    Read-only query layer over the recipe database.

    Methods are designed to be directly callable from any frontend adapter
    (REST API, GraphQL, CLI, etc.) without any UI framework dependency.
    """

    def __init__(self, database: RecipeDatabase) -> None:
        self._db = database

    def search_by_keyword(self, query_string: str) -> dict[str, dict]:
        """
        Perform a case-insensitive substring evaluation across recipe
        names and descriptions.

        Returns a dict of matching recipe_id → recipe_data pairs.
        """
        if not query_string or not query_string.strip():
            return {}

        query_lower = query_string.strip().lower()
        all_recipes = self._db.get_all()
        results = {}

        for recipe_id, recipe_data in all_recipes.items():
            name = recipe_data.get("name", "").lower()
            description = recipe_data.get("description", "").lower()

            if query_lower in name or query_lower in description:
                results[recipe_id] = recipe_data

        logger.debug(
            "search_by_keyword('%s'): %d matches out of %d records",
            query_string, len(results), len(all_recipes),
        )
        return results

    def filter_by_tag(self, tag_name: str) -> dict[str, dict]:
        """
        Return all records containing an exact match inside their tags array.

        The comparison is case-sensitive to match the canonical tag format
        (e.g., "High-Protein", "Keto-Friendly").
        """
        if not tag_name or not tag_name.strip():
            return {}

        tag = tag_name.strip()
        all_recipes = self._db.get_all()
        results = {}

        for recipe_id, recipe_data in all_recipes.items():
            tags = recipe_data.get("tags", [])
            if tag in tags:
                results[recipe_id] = recipe_data

        logger.debug(
            "filter_by_tag('%s'): %d matches out of %d records",
            tag_name, len(results), len(all_recipes),
        )
        return results

    def get_all_recipes(self) -> dict[str, dict]:
        """Return the entire current structured collection."""
        return self._db.get_all()
