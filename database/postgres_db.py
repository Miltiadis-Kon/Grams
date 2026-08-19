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
    Thread-safe database for recipe records.
    Uses PostgreSQL when available; automatically falls back to local SQLite (data/recipes.db).
    """

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name
        self._lock = threading.Lock()
        self._use_sqlite = False
        self._sqlite_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "recipes.db")

        # Try connecting to PostgreSQL first
        if HAS_PSYCOPG2:
            try:
                conn = _get_connection()
                conn.close()
                logger.info("RecipeDatabase connected to PostgreSQL for table: %s", self._table_name)
                return
            except Exception as exc:
                logger.info("PostgreSQL unavailable (%s); falling back to local SQLite (data/recipes.db).", exc)

        self._use_sqlite = True
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initialize local SQLite tables and indices."""
        import sqlite3
        os.makedirs(os.path.dirname(self._sqlite_path), exist_ok=True)
        with sqlite3.connect(self._sqlite_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    recipe_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT,
                    description TEXT,
                    macros TEXT,
                    ingredients TEXT,
                    instructions TEXT,
                    tags TEXT,
                    added_on TEXT,
                    transcript TEXT,
                    last_processed TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Auto-migrate columns if missing
            for col in ["metadata", "transcript", "last_processed"]:
                try:
                    conn.execute(f"ALTER TABLE {self._table_name} ADD COLUMN {col} TEXT;")
                except Exception:
                    pass
            conn.commit()
        logger.info("RecipeDatabase SQLite initialized for table: %s at %s", self._table_name, self._sqlite_path)

    # Internal helpers

    def _row_to_dict(self, row: dict) -> dict:
        """Convert a PostgreSQL/SQLite record into canonical recipe JSON structure."""
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

        metadata = row.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        if not metadata:
            metadata = {
                "transcript": row.get("transcript") or "",
                "description": row.get("description") or "",
            }

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
            "metadata": metadata,
        }

    # Public API

    def exists(self, recipe_id: str) -> bool:
        """O(1) check whether a recipe ID is already stored."""
        if self._use_sqlite:
            import sqlite3
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    cur = conn.cursor()
                    cur.execute(f"SELECT 1 FROM {self._table_name} WHERE recipe_id = ? LIMIT 1", (recipe_id,))
                    return cur.fetchone() is not None

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

    def insert(self, recipe_id: str, recipe, update_last_processed: bool = True) -> None:
        """Insert a new recipe record."""
        recipe_dict = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe
        transcript_val = recipe_dict.get("transcript", "")
        desc_val = recipe_dict.get("description", "")
        metadata_val = recipe_dict.get("metadata") or {"transcript": transcript_val, "description": desc_val}
        last_proc_val = recipe_dict.get("last_processed") if update_last_processed else ""

        if self._use_sqlite:
            import sqlite3
            import datetime
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            lp_to_write = now_iso if (update_last_processed and not last_proc_val) else (last_proc_val or (now_iso if update_last_processed else ""))
            data = (
                recipe_id,
                recipe_dict.get("name"),
                recipe_dict.get("url"),
                desc_val,
                json.dumps(recipe_dict.get("macros", {})),
                json.dumps(recipe_dict.get("ingredients", [])),
                json.dumps(recipe_dict.get("instructions", [])),
                json.dumps(recipe_dict.get("tags", [])),
                recipe_dict.get("added_on"),
                transcript_val,
                lp_to_write,
                json.dumps(metadata_val),
                now_iso,
                now_iso,
            )
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    conn.execute(
                        f"""
                        INSERT INTO {self._table_name}
                            (recipe_id, name, url, description, macros, ingredients, instructions, tags, added_on, transcript, last_processed, metadata, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        data
                    )
                    conn.commit()
            logger.info("Inserted recipe '%s' to SQLite table '%s'", recipe_id, self._table_name)
            return

        conn = None
        data = (
            recipe_id,
            recipe_dict.get("name"),
            recipe_dict.get("url"),
            desc_val,
            json.dumps(recipe_dict.get("macros", {})),
            json.dumps(recipe_dict.get("ingredients", [])),
            json.dumps(recipe_dict.get("instructions", [])),
            json.dumps(recipe_dict.get("tags", [])),
            recipe_dict.get("added_on"),
            transcript_val,
            json.dumps(metadata_val),
        )
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        if update_last_processed:
                            cur.execute(
                                f"""
                                INSERT INTO {self._table_name}
                                    (recipe_id, name, url, description, macros, ingredients, instructions, tags, added_on, transcript, metadata, last_processed)
                                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, NOW())
                                """,
                                data
                            )
                        else:
                            cur.execute(
                                f"""
                                INSERT INTO {self._table_name}
                                    (recipe_id, name, url, description, macros, ingredients, instructions, tags, added_on, transcript, metadata)
                                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
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

    def update(self, recipe_id: str, recipe_data: dict, update_last_processed: bool = True) -> None:
        """Update an existing recipe record."""
        import datetime
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        transcript_val = recipe_data.get("transcript", "")
        desc_val = recipe_data.get("description", "")
        metadata_val = recipe_data.get("metadata") or {"transcript": transcript_val, "description": desc_val}

        if self._use_sqlite:
            import sqlite3
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    if update_last_processed:
                        conn.execute(
                            f"""
                            UPDATE {self._table_name}
                            SET name=?, url=?, description=?,
                                macros=?, ingredients=?,
                                instructions=?, tags=?,
                                added_on=?, transcript=?,
                                last_processed=?, metadata=?, updated_at=?
                            WHERE recipe_id=?
                            """,
                            (
                                recipe_data.get("name"),
                                recipe_data.get("url"),
                                desc_val,
                                json.dumps(recipe_data.get("macros", {})),
                                json.dumps(recipe_data.get("ingredients", [])),
                                json.dumps(recipe_data.get("instructions", [])),
                                json.dumps(recipe_data.get("tags", [])),
                                recipe_data.get("added_on"),
                                transcript_val,
                                now_iso,
                                json.dumps(metadata_val),
                                now_iso,
                                recipe_id,
                            )
                        )
                    else:
                        conn.execute(
                            f"""
                            UPDATE {self._table_name}
                            SET name=?, url=?, description=?,
                                macros=?, ingredients=?,
                                instructions=?, tags=?,
                                added_on=?, transcript=?,
                                metadata=?, updated_at=?
                            WHERE recipe_id=?
                            """,
                            (
                                recipe_data.get("name"),
                                recipe_data.get("url"),
                                desc_val,
                                json.dumps(recipe_data.get("macros", {})),
                                json.dumps(recipe_data.get("ingredients", [])),
                                json.dumps(recipe_data.get("instructions", [])),
                                json.dumps(recipe_data.get("tags", [])),
                                recipe_data.get("added_on"),
                                transcript_val,
                                json.dumps(metadata_val),
                                now_iso,
                                recipe_id,
                            )
                        )
                    conn.commit()
            logger.info("Updated recipe '%s' in SQLite table '%s' (update_last_processed=%s)", recipe_id, self._table_name, update_last_processed)
            return

        conn = None
        with self._lock:
            try:
                conn = _get_connection()
                with conn:
                    with conn.cursor() as cur:
                        if update_last_processed:
                            cur.execute(
                                f"""
                                UPDATE {self._table_name}
                                SET name=%s, url=%s, description=%s,
                                    macros=%s::jsonb, ingredients=%s::jsonb,
                                    instructions=%s::jsonb, tags=%s::jsonb,
                                    added_on=%s, transcript=%s, metadata=%s::jsonb,
                                    last_processed=NOW(), updated_at=%s
                                WHERE recipe_id=%s
                                """,
                                (
                                    recipe_data.get("name"),
                                    recipe_data.get("url"),
                                    desc_val,
                                    json.dumps(recipe_data.get("macros", {})),
                                    json.dumps(recipe_data.get("ingredients", [])),
                                    json.dumps(recipe_data.get("instructions", [])),
                                    json.dumps(recipe_data.get("tags", [])),
                                    recipe_data.get("added_on"),
                                    transcript_val,
                                    json.dumps(metadata_val),
                                    now_iso,
                                    recipe_id,
                                )
                            )
                        else:
                            cur.execute(
                                f"""
                                UPDATE {self._table_name}
                                SET name=%s, url=%s, description=%s,
                                    macros=%s::jsonb, ingredients=%s::jsonb,
                                    instructions=%s::jsonb, tags=%s::jsonb,
                                    added_on=%s, transcript=%s, metadata=%s::jsonb,
                                    updated_at=%s
                                WHERE recipe_id=%s
                                """,
                                (
                                    recipe_data.get("name"),
                                    recipe_data.get("url"),
                                    desc_val,
                                    json.dumps(recipe_data.get("macros", {})),
                                    json.dumps(recipe_data.get("ingredients", [])),
                                    json.dumps(recipe_data.get("instructions", [])),
                                    json.dumps(recipe_data.get("tags", [])),
                                    recipe_data.get("added_on"),
                                    transcript_val,
                                    json.dumps(metadata_val),
                                    now_iso,
                                    recipe_id,
                                )
                            )
                logger.info("Updated recipe '%s' in table '%s' (update_last_processed=%s)", recipe_id, self._table_name, update_last_processed)
            except Exception as exc:
                logger.error("update() failed for table '%s': %s", self._table_name, exc)
                raise
            finally:
                if conn:
                    conn.close()

    def get(self, recipe_id: str) -> Optional[dict]:
        """Retrieve a single recipe by its ID, or None if not found."""
        if self._use_sqlite:
            import sqlite3
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(f"SELECT * FROM {self._table_name} WHERE recipe_id = ?", (recipe_id,))
                    row = cur.fetchone()
                    if row:
                        return self._row_to_dict(dict(row))
                    return None

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
        if self._use_sqlite:
            import sqlite3
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(f"SELECT * FROM {self._table_name}")
                    rows = cur.fetchall()
                    return {row["recipe_id"]: self._row_to_dict(dict(row)) for row in rows}

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
        if self._use_sqlite:
            import sqlite3
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    cur = conn.cursor()
                    cur.execute(f"SELECT COUNT(*) FROM {self._table_name}")
                    res = cur.fetchone()
                    return res[0] if res else 0

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
        if self._use_sqlite:
            import sqlite3
            with self._lock:
                with sqlite3.connect(self._sqlite_path) as conn:
                    cur = conn.cursor()
                    cur.execute(f"DELETE FROM {self._table_name} WHERE recipe_id = ?", (recipe_id,))
                    deleted = cur.rowcount > 0
                    conn.commit()
                    return deleted

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
        backend = "SQLite" if self._use_sqlite else "PostgreSQL"
        return f"<RecipeDatabase backend={backend} table={self._table_name}>"

