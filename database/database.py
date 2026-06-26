"""
Persistent Supabase client database engine for recipe records.

Provides O(1) lookups and Supabase cloud storage.
Requires SUPABASE_URL and SUPABASE_KEY to be configured in the environment.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from .models import Recipe

logger = logging.getLogger(__name__)

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False


class RecipeDatabase:
    """
    Thread-safe, Supabase-backed database.
    """

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name
        self._lock = threading.Lock()
        
        if not HAS_SUPABASE:
            raise ImportError(
                "supabase package is not installed. "
                "Please run `pip install supabase` to enable the Supabase backend."
            )

        # Detect environment database configuration
        self._supabase_url = os.environ.get("SUPABASE_URL")
        self._supabase_key = os.environ.get("SUPABASE_KEY")
        if not self._supabase_url or not self._supabase_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY environment variables are required!\n"
                "Please specify them in your .env file or environment variables."
            )
            
        logger.info("Initializing RecipeDatabase with Supabase backend for table: %s", self._table_name)
        self._client: Client = create_client(self._supabase_url, self._supabase_key)

    def _row_to_dict(self, row: dict) -> dict:
        """Convert a Supabase record into canonical recipe JSON structure."""
        return {
            "name": row.get("name"),
            "url": row.get("url"),
            "description": row.get("description"),
            "macros": row.get("macros"),
            "ingredients": row.get("ingredients"),
            "tags": row.get("tags"),
            "added_on": row.get("added_on"),
        }

    # ── Public API ───────────────────────────────────

    def exists(self, recipe_id: str) -> bool:
        """O(1) check whether a recipe ID is already stored."""
        with self._lock:
            try:
                response = self._client.table(self._table_name).select("recipe_id").eq("recipe_id", recipe_id).execute()
                return len(response.data) > 0
            except Exception as exc:
                logger.error("Supabase exists() query failed for table '%s': %s", self._table_name, exc)
                return False

    def insert(self, recipe_id: str, recipe: Recipe | dict) -> None:
        """
        Insert a new recipe record and persist.
        """
        recipe_dict = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe
        data = {
            "recipe_id": recipe_id,
            "name": recipe_dict.get("name"),
            "url": recipe_dict.get("url"),
            "description": recipe_dict.get("description"),
            "macros": recipe_dict.get("macros", {}),
            "ingredients": recipe_dict.get("ingredients", []),
            "tags": recipe_dict.get("tags", []),
            "added_on": recipe_dict.get("added_on")
        }

        with self._lock:
            try:
                self._client.table(self._table_name).insert(data).execute()
                logger.info("Inserted recipe '%s' to Supabase table '%s'", recipe_id, self._table_name)
            except Exception as exc:
                exc_str = str(exc)
                if "23505" in exc_str or "already exists" in exc_str.lower():
                    raise ValueError(f"Recipe '{recipe_id}' already exists in database") from exc
                logger.error("Supabase insert() failed for table '%s': %s", self._table_name, exc)
                raise

    def update(self, recipe_id: str, recipe_data: dict) -> None:
        """
        Update an existing recipe record and persist.
        """
        data = {
            "name": recipe_data.get("name"),
            "url": recipe_data.get("url"),
            "description": recipe_data.get("description"),
            "macros": recipe_data.get("macros", {}),
            "ingredients": recipe_data.get("ingredients", []),
            "tags": recipe_data.get("tags", []),
            "added_on": recipe_data.get("added_on")
        }

        with self._lock:
            try:
                self._client.table(self._table_name).update(data).eq("recipe_id", recipe_id).execute()
                logger.info("Updated recipe '%s' in Supabase table '%s'", recipe_id, self._table_name)
            except Exception as exc:
                logger.error("Supabase update() failed for table '%s': %s", self._table_name, exc)
                raise

    def get(self, recipe_id: str) -> Optional[dict]:
        """Retrieve a single recipe by its ID, or None if not found."""
        with self._lock:
            try:
                response = self._client.table(self._table_name).select("*").eq("recipe_id", recipe_id).execute()
                if response.data:
                    return self._row_to_dict(response.data[0])
                return None
            except Exception as exc:
                logger.error("Supabase get() failed for table '%s': %s", self._table_name, exc)
                return None

    def get_all(self) -> dict[str, dict]:
        """Return the entire recipe collection."""
        with self._lock:
            try:
                response = self._client.table(self._table_name).select("*").execute()
                return {row["recipe_id"]: self._row_to_dict(row) for row in response.data}
            except Exception as exc:
                logger.error("Supabase get_all() failed for table '%s': %s", self._table_name, exc)
                return {}

    def count(self) -> int:
        """Return the number of stored recipes."""
        with self._lock:
            try:
                response = self._client.table(self._table_name).select("*", count="exact").execute()
                if response.count is not None:
                    return response.count
                return len(response.data)
            except Exception as exc:
                logger.error("Supabase count() failed for table '%s': %s", self._table_name, exc)
                return 0

    def delete(self, recipe_id: str) -> bool:
        """Remove a recipe by its ID from the database. Returns True if removed, False otherwise."""
        with self._lock:
            try:
                response = self._client.table(self._table_name).delete().eq("recipe_id", recipe_id).execute()
                deleted = len(response.data) > 0
                if deleted:
                    logger.info("Deleted recipe '%s' from Supabase table '%s'", recipe_id, self._table_name)
                return deleted
            except Exception as exc:
                logger.error("Supabase delete() failed for table '%s': %s", self._table_name, exc)
                return False

    def __repr__(self) -> str:
        return f"<RecipeDatabase backend=Supabase table={self._table_name}>"
