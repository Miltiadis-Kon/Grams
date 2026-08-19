"""
PostgreSQL-backed database engine for recipe records.

Drop-in replacement for the Supabase RecipeDatabase.
Requires DATABASE_URL or individual PG_* environment variables.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

from .models import Recipe

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def _get_connection():
    """Create a new psycopg2 connection from environment variables."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("PG_DB", "grams"),
        user=os.environ.get("PG_USER", "grams"),
        password=os.environ.get("PG_PASSWORD", "grams"),
    )


class RecipeDatabase:
    """
    Thread-safe, PostgreSQL-backed database for recipe records.

    Maintains the same public API as the old Supabase-backed version.
    """

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name
        self._lock = threading.Lock()

        if not HAS_PSYCOPG2:
            raise ImportError(
                "psycopg2-binary is not installed. "
                "Please run `pip install psycopg2-binary` to enable the PostgreSQL backend."
            )

        # Validate connection on startup to fail fast
        try:
            conn = _get_connection()
            conn.close()
            logger.info("RecipeDatabase connected to PostgreSQL for table: %s", self._table_name)
        except Exception as exc:
            raise ConnectionError(
                f"Cannot connect to PostgreSQL. Check DATABASE_URL or PG_* env vars.\n{exc}"
            ) from exc

    # Internal helpers

    def _row_to_dict(self, row: dict) -> dict:
        """Convert a PostgreSQL record into canonical recipe JSON structure."""
        macros = row.get("macros")
        if isinstance(macros, str):
            macros = json.loads(macros)

        ingredients = row.get("ingredients")
        if isinstance(ingredients, str):
            ingredients = json.loads(ingredients)

        tags = row.get("tags")
        if isinstance(tags, str):
            tags = json.loads(tags)

        instructions = row.get("instructions")
        if isinstance(instructions, str):
            instructions = json.loads(instructions)

        last_proc = row.get("last_processed")
        last_proc_str = last_proc.isoformat() if hasattr(last_proc, "isoformat") else (str(last_proc) if last_proc else "")

        return {
            "name": row.get("name"),
            "url": row.get("url"),
            "description": row.get("description"),
            "macros": macros,
            "ingredients": ingredients,
            "instructions": instructions or [],
            "tags": tags,
            "added_on": row.get("added_on"),
            "transcript": row.get("transcript") or "",
            "last_processed": last_proc_str,
        }

    # Public API

    def exists(self, recipe_id: str) -> bool:
        """O(1) check whether a recipe ID is already stored."""
        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"SELECT 1 FROM {self._table_name} WHERE recipe_id = %s LIMIT 1",
                            (recipe_id,)
                        )
                        return cur.fetchone() is not None
            except Exception as exc:
                logger.error("exists() failed for table '%s': %s", self._table_name, exc)
                return False
            finally:
                if conn:
                    conn.close()

    def insert(self, recipe_id: str, recipe) -> None:
        """Insert a new recipe record."""
        recipe_dict = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe
        data = (
            recipe_id,
            recipe_dict.get("name"),
            recipe_dict.get("url"),
            recipe_dict.get("description"),
            json.dumps(recipe_dict.get("macros", {})),
            json.dumps(recipe_dict.get("ingredients", [])),
            json.dumps(recipe_dict.get("instructions", [])),
            json.dumps(recipe_dict.get("tags", [])),
            recipe_dict.get("added_on"),
            recipe_dict.get("transcript", ""),
        )

        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            INSERT INTO {self._table_name}
                                (recipe_id, name, url, description, macros, ingredients, instructions, tags, added_on, transcript, last_processed)
                            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, NOW())
                            """,
                            data
                        )
                logger.info("Inserted recipe '%s' to table '%s'", recipe_id, self._table_name)
            except psycopg2.errors.UniqueViolation:
                raise ValueError(f"Recipe '{recipe_id}' already exists in database")
            except Exception as exc:
                logger.error("insert() failed for table '%s': %s", self._table_name, exc)
                raise
            finally:
                if conn:
                    conn.close()

    def update(self, recipe_id: str, recipe_data: dict) -> None:
        """Update an existing recipe record."""
        import datetime
        data = (
            recipe_data.get("name"),
            recipe_data.get("url"),
            recipe_data.get("description"),
            json.dumps(recipe_data.get("macros", {})),
            json.dumps(recipe_data.get("ingredients", [])),
            json.dumps(recipe_data.get("instructions", [])),
            json.dumps(recipe_data.get("tags", [])),
            recipe_data.get("added_on"),
            recipe_data.get("transcript", ""),
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            recipe_id,
        )

        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            UPDATE {self._table_name}
                            SET name=%s, url=%s, description=%s,
                                macros=%s::jsonb, ingredients=%s::jsonb,
                                instructions=%s::jsonb, tags=%s::jsonb,
                                added_on=%s, transcript=%s,
                                last_processed=NOW(), updated_at=%s
                            WHERE recipe_id=%s
                            """,
                            data
                        )
                logger.info("Updated recipe '%s' in table '%s'", recipe_id, self._table_name)
            except Exception as exc:
                logger.error("update() failed for table '%s': %s", self._table_name, exc)
                raise
            finally:
                if conn:
                    conn.close()

    def get(self, recipe_id: str) -> Optional[dict]:
        """Retrieve a single recipe by its ID, or None if not found."""
        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            f"SELECT * FROM {self._table_name} WHERE recipe_id = %s",
                            (recipe_id,)
                        )
                        row = cur.fetchone()
                        if row:
                            return self._row_to_dict(dict(row))
                        return None
            except Exception as exc:
                logger.error("get() failed for table '%s': %s", self._table_name, exc)
                return None
            finally:
                if conn:
                    conn.close()

    def get_all(self) -> dict[str, dict]:
        """Return the entire recipe collection."""
        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(f"SELECT * FROM {self._table_name}")
                        rows = cur.fetchall()
                        return {row["recipe_id"]: self._row_to_dict(dict(row)) for row in rows}
            except Exception as exc:
                logger.error("get_all() failed for table '%s': %s", self._table_name, exc)
                return {}
            finally:
                if conn:
                    conn.close()

    def count(self) -> int:
        """Return the number of stored recipes."""
        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT COUNT(*) FROM {self._table_name}")
                        result = cur.fetchone()
                        return result[0] if result else 0
            except Exception as exc:
                logger.error("count() failed for table '%s': %s", self._table_name, exc)
                return 0
            finally:
                if conn:
                    conn.close()

    def delete(self, recipe_id: str) -> bool:
        """Remove a recipe by its ID. Returns True if removed, False otherwise."""
        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"DELETE FROM {self._table_name} WHERE recipe_id = %s RETURNING recipe_id",
                            (recipe_id,)
                        )
                        deleted = cur.fetchone() is not None
                        if deleted:
                            logger.info("Deleted recipe '%s' from table '%s'", recipe_id, self._table_name)
                        return deleted
            except Exception as exc:
                logger.error("delete() failed for table '%s': %s", self._table_name, exc)
                return False
            finally:
                if conn:
                    conn.close()

    def __repr__(self) -> str:
        return f"<RecipeDatabase backend=PostgreSQL table={self._table_name}>"
