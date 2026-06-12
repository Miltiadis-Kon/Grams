"""
Persistent JSON database engine for recipe records.

Provides O(1) lookups via dict-based primary keys, atomic writes to prevent
corruption, and thread-safe access for concurrent usage scenarios.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Optional

from .models import Recipe

logger = logging.getLogger(__name__)


class RecipeDatabase:
    """
    Thread-safe, file-backed JSON database indexed by recipe ID.

    The on-disk format is a flat JSON object keyed by recipe ID strings:
    {
        "RECIPE_ID_STRING": { ... recipe fields ... },
        ...
    }
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    # ── Persistence ──────────────────────────────────

    def _load(self) -> None:
        """Load the database from disk into memory."""
        if os.path.exists(self._db_path):
            try:
                with open(self._db_path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
                logger.info(
                    "Loaded %d recipes from %s", len(self._data), self._db_path
                )
            except (json.JSONDecodeError, IOError) as exc:
                logger.error("Failed to load database: %s — starting fresh", exc)
                self._data = {}
        else:
            logger.info("No existing database at %s — starting fresh", self._db_path)
            self._data = {}

    def _save(self) -> None:
        """
        Atomically write the in-memory data to disk.

        Uses a temporary file + os.replace to guarantee that the database
        file is never left in a partially-written state.
        """
        dir_name = os.path.dirname(self._db_path) or "."
        os.makedirs(dir_name, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self._db_path)
        except Exception:
            # Clean up the temp file if replace fails
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ── Public API ───────────────────────────────────

    def exists(self, recipe_id: str) -> bool:
        """O(1) check whether a recipe ID is already stored."""
        with self._lock:
            return recipe_id in self._data

    def insert(self, recipe_id: str, recipe: Recipe) -> None:
        """
        Insert a new recipe record and persist to disk.

        Raises ValueError if the ID already exists (use `exists()` first).
        """
        with self._lock:
            if recipe_id in self._data:
                raise ValueError(f"Recipe '{recipe_id}' already exists in database")
            self._data[recipe_id] = recipe.to_dict()
            self._save()
            logger.info("Inserted recipe '%s': %s", recipe_id, recipe.name)

    def get(self, recipe_id: str) -> Optional[dict]:
        """Retrieve a single recipe by its ID, or None if not found."""
        with self._lock:
            return self._data.get(recipe_id)

    def get_all(self) -> dict[str, dict]:
        """Return the entire recipe collection (shallow copy)."""
        with self._lock:
            return dict(self._data)

    def count(self) -> int:
        """Return the number of stored recipes."""
        with self._lock:
            return len(self._data)

    def __repr__(self) -> str:
        return f"<RecipeDatabase records={self.count()} path='{self._db_path}'>"
