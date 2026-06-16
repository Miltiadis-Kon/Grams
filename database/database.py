"""
Persistent JSON or PostgreSQL database engine for recipe records.

Provides O(1) lookups, atomic writes, and dual-backend support:
- PostgreSQL (when DATABASE_URL is set in environment)
- Local JSON file (when DATABASE_URL is not set)
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

# Conditional import to allow local fallback without installing psycopg2
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class RecipeDatabase:
    """
    Thread-safe, dual-backed database supporting both PostgreSQL and JSON.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        
        # Detect environment database configuration
        self._db_url = os.environ.get("DATABASE_URL")
        self._is_postgres = bool(self._db_url)
        
        # Map table name based on filepath
        if "not_added_recipes" in db_path:
            self._table_name = "not_added_recipes"
        else:
            self._table_name = "recipes"
            
        self._data: dict[str, dict] = {}
        
        if self._is_postgres:
            logger.info("Initializing RecipeDatabase with PostgreSQL backend for table: %s", self._table_name)
            self._init_db()
        else:
            logger.info("Initializing RecipeDatabase with Local JSON backend: %s", self._db_path)
            self._load()

    # ── Database Connection ──────────────────────────

    def _get_conn(self):
        if not HAS_PSYCOPG2:
            raise ImportError(
                "DATABASE_URL environment variable is set, but psycopg2 is not installed. "
                "Please run `pip install psycopg2-binary` to enable PostgreSQL backend."
            )
        url = self._db_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)

    def _init_db(self) -> None:
        """Ensure PostgreSQL table exists."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self._table_name} (
                        recipe_id VARCHAR PRIMARY KEY,
                        name VARCHAR,
                        url VARCHAR,
                        description TEXT,
                        macros JSONB,
                        ingredients JSONB,
                        tags JSONB,
                        added_on VARCHAR,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            conn.commit()
            logger.info("Ensured PostgreSQL table '%s' is created", self._table_name)
        except Exception as exc:
            logger.error("Failed to initialize PostgreSQL database: %s", exc)
            raise
        finally:
            conn.close()

    # ── Persistence (JSON fallback only) ─────────────

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
        """
        dir_name = os.path.dirname(self._db_path) or "."
        os.makedirs(dir_name, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self._db_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _row_to_dict(self, row) -> dict:
        """Convert a SQL Row into canonical recipe JSON structure."""
        return {
            "name": row["name"],
            "url": row["url"],
            "description": row["description"],
            "macros": row["macros"],
            "ingredients": row["ingredients"],
            "tags": row["tags"],
            "added_on": row["added_on"],
        }

    # ── Public API ───────────────────────────────────

    def exists(self, recipe_id: str) -> bool:
        """O(1) check whether a recipe ID is already stored."""
        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT 1 FROM {self._table_name} WHERE recipe_id = %s LIMIT 1;", (recipe_id,))
                    return cur.fetchone() is not None
            except Exception as exc:
                logger.error("PostgreSQL exists() query failed: %s", exc)
                return False
            finally:
                conn.close()
        else:
            with self._lock:
                return recipe_id in self._data

    def insert(self, recipe_id: str, recipe: Recipe | dict) -> None:
        """
        Insert a new recipe record and persist.
        """
        recipe_dict = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe

        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    # Check existence
                    cur.execute(f"SELECT 1 FROM {self._table_name} WHERE recipe_id = %s LIMIT 1;", (recipe_id,))
                    if cur.fetchone() is not None:
                        raise ValueError(f"Recipe '{recipe_id}' already exists in database")

                    cur.execute(
                        f"""
                        INSERT INTO {self._table_name} (recipe_id, name, url, description, macros, ingredients, tags, added_on)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            recipe_id,
                            recipe_dict.get("name"),
                            recipe_dict.get("url"),
                            recipe_dict.get("description"),
                            json.dumps(recipe_dict.get("macros", {})),
                            json.dumps(recipe_dict.get("ingredients", [])),
                            json.dumps(recipe_dict.get("tags", [])),
                            recipe_dict.get("added_on")
                        )
                    )
                conn.commit()
                logger.info("Inserted recipe '%s' to PostgreSQL", recipe_id)
            finally:
                conn.close()
        else:
            with self._lock:
                if recipe_id in self._data:
                    raise ValueError(f"Recipe '{recipe_id}' already exists in database")
                self._data[recipe_id] = recipe_dict
                self._save()
                logger.info("Inserted recipe '%s': %s", recipe_id, recipe_dict.get("name"))

    def update(self, recipe_id: str, recipe_data: dict) -> None:
        """
        Update an existing recipe record and persist.
        """
        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {self._table_name}
                        SET name = %s, url = %s, description = %s, macros = %s, ingredients = %s, tags = %s, added_on = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE recipe_id = %s;
                        """,
                        (
                            recipe_data.get("name"),
                            recipe_data.get("url"),
                            recipe_data.get("description"),
                            json.dumps(recipe_data.get("macros", {})),
                            json.dumps(recipe_data.get("ingredients", [])),
                            json.dumps(recipe_data.get("tags", [])),
                            recipe_data.get("added_on"),
                            recipe_id
                        )
                    )
                conn.commit()
                logger.info("Updated recipe '%s' in PostgreSQL", recipe_id)
            finally:
                conn.close()
        else:
            with self._lock:
                self._data[recipe_id] = recipe_data
                self._save()
                logger.info("Updated recipe '%s' in JSON database", recipe_id)

    def get(self, recipe_id: str) -> Optional[dict]:
        """Retrieve a single recipe by its ID, or None if not found."""
        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(f"SELECT * FROM {self._table_name} WHERE recipe_id = %s LIMIT 1;", (recipe_id,))
                    row = cur.fetchone()
                    if row:
                        return self._row_to_dict(row)
                    return None
            except Exception as exc:
                logger.error("PostgreSQL get() query failed: %s", exc)
                return None
            finally:
                conn.close()
        else:
            with self._lock:
                return self._data.get(recipe_id)

    def get_all(self) -> dict[str, dict]:
        """Return the entire recipe collection (shallow copy)."""
        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(f"SELECT * FROM {self._table_name};")
                    rows = cur.fetchall()
                    return {row["recipe_id"]: self._row_to_dict(row) for row in rows}
            except Exception as exc:
                logger.error("PostgreSQL get_all() query failed: %s", exc)
                return {}
            finally:
                conn.close()
        else:
            with self._lock:
                return dict(self._data)

    def count(self) -> int:
        """Return the number of stored recipes."""
        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {self._table_name};")
                    return cur.fetchone()[0]
            except Exception as exc:
                logger.error("PostgreSQL count() query failed: %s", exc)
                return 0
            finally:
                conn.close()
        else:
            with self._lock:
                return len(self._data)

    def delete(self, recipe_id: str) -> bool:
        """Remove a recipe by its ID from the database. Returns True if removed, False otherwise."""
        if self._is_postgres:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {self._table_name} WHERE recipe_id = %s;", (recipe_id,))
                    deleted = cur.rowcount > 0
                conn.commit()
                if deleted:
                    logger.info("Deleted recipe '%s' from PostgreSQL", recipe_id)
                return deleted
            except Exception as exc:
                logger.error("PostgreSQL delete() query failed: %s", exc)
                return False
            finally:
                conn.close()
        else:
            with self._lock:
                if recipe_id in self._data:
                    del self._data[recipe_id]
                    self._save()
                    logger.info("Deleted recipe '%s'", recipe_id)
                    return True
                return False

    def __repr__(self) -> str:
        backend = "PostgreSQL" if self._is_postgres else "JSON"
        return f"<RecipeDatabase backend={backend} records={self.count()} path='{self._db_path}'>"
